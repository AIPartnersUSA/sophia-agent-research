using System;
using System.Collections;
using System.Collections.Generic;
using System.Text;
using LiveKit;
using LiveKit.Proto;
using UnityEngine;
using UnityEngine.Networking;

/// <summary>
/// Phase 1 voice loop: connect to sophia-agent's LiveKit room, publish the
/// glasses microphone, subscribe to Sophia's TTS, log everything.
///
/// Modularity (per AGENTS.md): this script does CONNECTION + AUDIO only.
/// UI panels (state pill, transcript, RAG sources) are separate
/// MonoBehaviours added in Phase 2.
///
/// Wire-up in Unity Editor:
///   1. Create an empty GameObject in the scene, name it "SophiaConnection".
///   2. Add this script as a component.
///   3. Drag the SophiaConfig.asset into the "Config" field in the Inspector.
///
/// Per CHAT.md turn 49: defaults to UNIQUE room name per launch
/// (Scenario B). Set SophiaConfig.roomName to a fixed value for
/// Scenario A (shared room).
/// </summary>
public class SophiaConnection : MonoBehaviour
{
    /// <summary>
    /// Fired whenever any subscribed text-stream message arrives.
    /// (topic, fromIdentity, jsonPayload). UI panels subscribe to this
    /// instead of reaching into Room handlers, so panels stay decoupled
    /// from connection lifecycle. Static so panels created later can
    /// still subscribe without a reference search.
    /// </summary>
    public static event Action<string, string, string> OnTextStreamMessage;

    [Header("Required")]
    [SerializeField] private SophiaConfig config;

    [Header("Audio Hosts (auto-created if blank)")]
    [Tooltip("GameObject to host the local mic AudioSource. " +
             "Auto-created on this object if left empty.")]
    [SerializeField] private GameObject micHost;

    [Tooltip("GameObject to host the remote (Sophia TTS) AudioSource. " +
             "Auto-created on this object if left empty.")]
    [SerializeField] private GameObject speakerHost;

    private Room _room;
    private string _resolvedRoom;
    private string _resolvedIdentity;
    private MicrophoneSource _micSource;
    private LocalAudioTrack _micTrack;

    // One child GameObject per remote audio track we play back. Keyed by the
    // track's publication SID so OnTrackUnsubscribed can find and destroy the
    // right one. Only AGENT audio tracks land here — other participants' raw
    // mics are skipped on purpose (see OnTrackSubscribed for the contract).
    private readonly Dictionary<string, GameObject> _remoteSpeakers = new();

    private void OnEnable()
    {
        if (config == null)
        {
            Debug.LogError("[Sophia] SophiaConfig is not assigned on " +
                "SophiaConnection. Assign Assets/Settings/SophiaConfig.asset " +
                "in the Inspector.");
            return;
        }

        if (micHost == null) micHost = gameObject;
        if (speakerHost == null) speakerHost = gameObject;

        // Resolve room name with two-layer precedence:
        //   1. SophiaSessionContext.RoomOverride (set by SessionPicker at runtime
        //      when the user typed a Team code; null otherwise)
        //   2. SophiaConfig.roomName (baked-in default from the .asset; usually
        //      empty so we fall through to UUID auto-generation)
        // Empty after both layers => generate unique-per-launch room (Private mode).
        string desiredRoom = SophiaSessionContext.RoomOverride ?? config.roomName;
        _resolvedRoom = string.IsNullOrWhiteSpace(desiredRoom)
            ? $"sophia-glasses-{Guid.NewGuid().ToString("N").Substring(0, 12)}"
            : desiredRoom.Trim();

        // Resolve identity: empty config field = generate unique per launch.
        _resolvedIdentity = string.IsNullOrWhiteSpace(config.participantIdentity)
            ? $"glasses-{Guid.NewGuid().ToString("N").Substring(0, 8)}"
            : config.participantIdentity.Trim();

        Debug.Log($"[Sophia] Starting. room='{_resolvedRoom}' identity='{_resolvedIdentity}' " +
                  $"server='{config.liveKitUrl}'");
        StartCoroutine(ConnectFlow());
    }

    private void OnDisable()
    {
        Cleanup("OnDisable");
    }

    /// <summary>
    /// Android system event: app sent to background (Home button, swipe-away
    /// from recents, screen lock). Disconnect cleanly so the SFU doesn't
    /// see a phantom participant. The voice loop does NOT auto-resume on
    /// unpause -- user has to re-enter via SessionPicker.
    /// </summary>
    private void OnApplicationPause(bool isPaused)
    {
        if (isPaused) Cleanup("OnApplicationPause");
    }

    /// <summary>
    /// Android system event: app being terminated by OS or Application.Quit().
    /// Same cleanup so the SFU sees a clean disconnect on the way out.
    /// </summary>
    private void OnApplicationQuit()
    {
        Cleanup("OnApplicationQuit");
    }

    /// <summary>
    /// Best-effort teardown of mic capture + room connection. Called from
    /// OnDisable / OnApplicationPause / OnApplicationQuit. Safe to call
    /// multiple times -- if already torn down, the null-conditional calls
    /// are no-ops.
    ///
    /// Note: LocalAudioTrack does not expose a Stop() method; tearing
    /// down MicrophoneSource + disconnecting the room is enough. The
    /// track is GC'd once references drop.
    /// </summary>
    private void Cleanup(string trigger)
    {
        try
        {
            _micSource?.Stop();
            _room?.Disconnect();

            // Tear down per-track speaker GameObjects we created in
            // OnTrackSubscribed. These hold AudioSource + AudioStream
            // bindings that need to be released cleanly so the next session
            // doesn't inherit ghost playback components.
            foreach (var kv in _remoteSpeakers)
            {
                if (kv.Value != null) Destroy(kv.Value);
            }
            _remoteSpeakers.Clear();

            Debug.Log($"[Sophia] Disconnected on {trigger}.");
        }
        catch (Exception e)
        {
            Debug.LogWarning($"[Sophia] Cleanup error ({trigger}): {e.Message}");
        }
    }

    private IEnumerator ConnectFlow()
    {
        // ---- Step 1: fetch a JWT from sophia-agent's token_mint ----
        string token = null;
        string serverUrl = config.liveKitUrl;

        var reqBody = Encoding.UTF8.GetBytes(BuildTokenRequestJson());
        using (var www = new UnityWebRequest(config.tokenEndpoint, "POST"))
        {
            www.uploadHandler = new UploadHandlerRaw(reqBody);
            www.downloadHandler = new DownloadHandlerBuffer();
            www.SetRequestHeader("Content-Type", "application/json");
            yield return www.SendWebRequest();

            if (www.result != UnityWebRequest.Result.Success)
            {
                Debug.LogError($"[Sophia] Token mint failed: {www.error} | " +
                               $"endpoint={config.tokenEndpoint} | " +
                               $"response={www.downloadHandler.text}");
                yield break;
            }

            var resp = JsonUtility.FromJson<TokenResponse>(www.downloadHandler.text);
            token = resp.token;
            // NOTE: do NOT override serverUrl with resp.url. The token_mint
            // reports the SFU URL from sophia-agent's own .env.local
            // (typically ws://localhost:7880 = the Mac's perspective).
            // External clients (Beam Pro on Tailscale) need their own
            // route to the SFU, which lives in SophiaConfig.liveKitUrl.
            Debug.Log($"[Sophia] Got token (len={token?.Length ?? 0}) for url={serverUrl}");
        }

        // ---- Step 2: connect to the room ----
        _room = new Room();
        _room.TrackSubscribed += OnTrackSubscribed;
        _room.TrackUnsubscribed += OnTrackUnsubscribed;
        _room.ParticipantConnected += p => Debug.Log($"[Sophia] Participant connected: {p.Identity}");
        _room.ParticipantDisconnected += p => Debug.Log($"[Sophia] Participant disconnected: {p.Identity}");
        _room.Disconnected += reason => Debug.LogWarning($"[Sophia] Room disconnected: {reason}");
        _room.ConnectionStateChanged += state => Debug.Log($"[Sophia] Connection state: {state}");

        // Subscribe to data-channel topics so the bottom-left events panel
        // equivalent will arrive here in Phase 2. For Phase 1 we just log
        // them.
        _room.RegisterTextStreamHandler("sophia.rag_result",
            (reader, identity) => StartCoroutine(LogTextStream("rag_result", reader, identity)));
        _room.RegisterTextStreamHandler("sophia.agent_events",
            (reader, identity) => StartCoroutine(LogTextStream("agent_events", reader, identity)));
        _room.RegisterTextStreamHandler("lk.transcription",
            (reader, identity) => StartCoroutine(LogTextStream("transcription", reader, identity)));

        // Room.Connect requires a RoomOptions argument (no overload without it).
        // Defaults are fine for Phase 1; we'll tune options (E2EE, adaptive
        // stream, etc.) in later phases if needed.
        // Disambiguate: both LiveKit and LiveKit.Proto define RoomOptions.
        // Room.Connect expects the top-level LiveKit.RoomOptions one.
        var connectOp = _room.Connect(serverUrl, token, new LiveKit.RoomOptions());
        yield return connectOp;

        if (connectOp.IsError)
        {
            // ConnectInstruction exposes only IsError (bool), not a message
            // string. Detailed errors land in Unity Console via the SDK's
            // own logging.
            Debug.LogError("[Sophia] Room.Connect failed (see SDK log above).");
            yield break;
        }
        Debug.Log($"[Sophia] Connected to room '{_resolvedRoom}'.");

        // ---- Step 3: publish the microphone ----
        // Request mic permission. On Android this triggers the runtime
        // permission prompt. On macOS Editor it's a no-op (the actual
        // grant is in System Settings > Privacy & Security > Microphone,
        // which the user has to do once per Unity install).
        yield return Application.RequestUserAuthorization(UserAuthorization.Microphone);
        if (!Application.HasUserAuthorization(UserAuthorization.Microphone))
        {
            Debug.LogError("[Sophia] Microphone permission not granted. " +
                "On macOS Editor: System Settings > Privacy & Security > " +
                "Microphone > enable Unity, then restart Unity. " +
                "On Beam Pro: Android runtime prompt should have appeared; " +
                "if denied, re-grant via the OS settings for the app.");
            yield break;
        }

        // Android permission race: Application.RequestUserAuthorization above
        // shows the system dialog but returns immediately on Android (doesn't
        // block on user response). A naive zero-wait check on Microphone.devices
        // returns empty because Android hasn't granted RECORD_AUDIO yet. Poll
        // up to 20s, allowing the user time to tap Allow. Path A from
        // livekit_doubts.md Q47 (Path B JNI bridge with a real callback is the
        // proper fix, deferred to Phase 2 hardening -- same JNI can also swap
        // the audio source to VOICE_COMMUNICATION for Android system AEC,
        // solving Q41/Q43 too).
        const float maxWaitSeconds = 20f;
        const float pollInterval = 0.2f;
        float elapsed = 0f;

        if (Microphone.devices == null || Microphone.devices.Length == 0)
        {
            Debug.Log($"[Sophia] No microphone devices yet. Waiting up to " +
                $"{maxWaitSeconds}s for Android to grant RECORD_AUDIO " +
                "(tap Allow on the permission dialog if visible).");
        }

        while (Microphone.devices == null || Microphone.devices.Length == 0)
        {
            if (elapsed >= maxWaitSeconds)
            {
                Debug.LogError($"[Sophia] No microphone devices found after " +
                    $"{maxWaitSeconds}s. User likely denied or ignored the " +
                    "permission dialog. Re-grant via OS settings (Android: " +
                    "App Info > Permissions > Microphone) or reinstall.");
                yield break;
            }
            yield return new WaitForSeconds(pollInterval);
            elapsed += pollInterval;
        }

        if (elapsed > 0f)
        {
            Debug.Log($"[Sophia] Microphone became available after {elapsed:F1}s.");
        }

        int micIdx = config.microphoneDeviceIndex;
        if (micIdx < 0 || micIdx >= Microphone.devices.Length) micIdx = 0;
        string micName = Microphone.devices[micIdx];
        Debug.Log($"[Sophia] Using microphone [{micIdx}] '{micName}' " +
                  $"(available: {string.Join(", ", Microphone.devices)})");

        _micSource = new MicrophoneSource(micName, micHost);
        _micTrack = LocalAudioTrack.CreateAudioTrack("sophia-mic", _micSource, _room);

        // TrackPublishOptions + TrackSource live in LiveKit.Proto namespace
        // (auto-generated from the LiveKit protobuf definitions). They're
        // imported via `using LiveKit.Proto;` at the top of this file.
        var pubOpts = new TrackPublishOptions { Source = TrackSource.SourceMicrophone };
        var pubOp = _room.LocalParticipant.PublishTrack(_micTrack, pubOpts);
        yield return pubOp;
        if (pubOp.IsError)
        {
            // PublishTrackInstruction also exposes only IsError, no message
            // string.
            Debug.LogError("[Sophia] Mic publish failed (see SDK log above).");
            yield break;
        }
        _micSource.Start();
        Debug.Log("[Sophia] Microphone publishing. You can speak now.");
    }

    private void OnTrackSubscribed(IRemoteTrack track, RemoteTrackPublication publication,
                                   RemoteParticipant participant)
    {
        Debug.Log($"[Sophia] Track subscribed: kind={track.Kind} " +
                  $"from participant='{participant?.Identity}' " +
                  $"sid={publication?.Sid}");

        if (track is not RemoteAudioTrack audioTrack) return;

        // Production contract for shared rooms (Scenario A): we play ONLY the
        // agent's TTS through this device's speakers. Other human participants'
        // raw mic tracks are intentionally NOT played back here -- in person they
        // speak to each other directly, and inside the agent loop their voice
        // reaches Sophia via the SFU's audio mix. Playing other users' mics
        // back through our own speaker would echo their voice at them, mix it
        // with Sophia's TTS, and create acoustic chaos. Each user's device
        // owns its own mic and its own speaker; the agent is the only voice
        // shared across devices.
        bool isAgent = !string.IsNullOrEmpty(participant?.Identity)
                       && participant.Identity.StartsWith("agent-");
        if (!isAgent)
        {
            Debug.Log($"[Sophia] Skipping playback for non-agent audio track from " +
                      $"'{participant?.Identity}' (room mate's mic; intentional).");
            return;
        }

        // Each remote audio track gets its OWN child GameObject so the
        // AudioSource + AudioStream + any future per-track audio filters live
        // in isolation. The MicrophoneSource the SDK uses for OUR mic capture
        // adds its own AudioSource + AudioProbe to micHost (typically the
        // parent SophiaConnection GameObject). Putting another AudioSource on
        // the SAME GameObject confuses AudioProbe.OnAudioFilterRead which can
        // only bind to one AudioSource at a time -- the symptom is that one
        // or the other silently stops playing, and in shared-room mode the
        // browser-mic track ended up winning the slot so Sophia's TTS got
        // dropped on the glasses speakers. Per-track child GameObject fixes
        // this once and for all and is the pattern the Phase 2 hardening
        // note has been calling for.
        var sid = publication?.Sid;
        if (string.IsNullOrEmpty(sid))
        {
            sid = Guid.NewGuid().ToString("N").Substring(0, 8);
        }
        var speakerName = $"SophiaSpeaker_{sid}";
        var speakerGO = new GameObject(speakerName);
        speakerGO.transform.SetParent(speakerHost.transform, false);

        var src = speakerGO.AddComponent<AudioSource>();
        src.loop = true;
        src.spatialBlend = 0f; // 2D, no positional audio
        // Constructing AudioStream wires the remote track's PCM into the
        // AudioSource. Hold no reference here -- the AudioStream's lifetime is
        // tied to the AudioSource's GameObject, which we destroy explicitly in
        // OnTrackUnsubscribed and Cleanup.
        new AudioStream(audioTrack, src);

        _remoteSpeakers[sid] = speakerGO;
        Debug.Log($"[Sophia] Agent audio wired to child GameObject '{speakerName}' " +
                  $"under parent '{speakerHost.name}'.");
    }

    private void OnTrackUnsubscribed(IRemoteTrack track, RemoteTrackPublication publication,
                                     RemoteParticipant participant)
    {
        Debug.Log($"[Sophia] Track unsubscribed: kind={track.Kind} " +
                  $"from participant='{participant?.Identity}'");

        var sid = publication?.Sid;
        if (string.IsNullOrEmpty(sid)) return;
        if (_remoteSpeakers.TryGetValue(sid, out var speakerGO))
        {
            if (speakerGO != null) Destroy(speakerGO);
            _remoteSpeakers.Remove(sid);
            Debug.Log($"[Sophia] Removed speaker for sid={sid}.");
        }
    }

    private IEnumerator LogTextStream(string topicTag, TextStreamReader reader, string identity)
    {
        // ReadIncremental delivers chunks as the sender writes them, so HUD text
        // appears in step with TTS audio (token-by-token) instead of all-at-once
        // when the stream closes. ReadAll() buffers everything until EOS -- that
        // is why HUD text used to lag behind speech, while the browser client
        // (which uses incremental reads) shows text in sync.
        //
        // For sophia.rag_result / sophia.agent_events the agent typically writes
        // a single JSON chunk then closes, so we still get one final emit there.
        // SophiaOverlayUI's JSON parsers are tolerant of missing keys, so any
        // intermediate partial-JSON chunk is a silent no-op until complete.
        var inc = reader.ReadIncremental();
        var accumulated = new StringBuilder();
        while (!inc.IsEos)
        {
            inc.Reset();
            yield return inc;
            if (inc.IsError)
            {
                Debug.LogWarning($"[Sophia][{topicTag}] stream errored mid-read; aborting.");
                break;
            }
            var chunk = inc.Text;
            if (string.IsNullOrEmpty(chunk)) continue;
            accumulated.Append(chunk);
            var snapshot = accumulated.ToString();
            try
            {
                OnTextStreamMessage?.Invoke(topicTag, identity, snapshot);
            }
            catch (Exception e)
            {
                Debug.LogWarning($"[Sophia] OnTextStreamMessage handler threw: {e.Message}");
            }
        }
        Debug.Log($"[Sophia][{topicTag}] from='{identity}' final={accumulated}");
    }

    private string BuildTokenRequestJson()
    {
        // Manual JSON build (3 short string fields, no need for a heavy serializer).
        // Matches sophia-agent/src/token_mint.py's TokenRequest schema.
        string Escape(string s) => s?.Replace("\\", "\\\\").Replace("\"", "\\\"") ?? "";
        var name = string.IsNullOrWhiteSpace(config.participantName)
            ? "Sophia Glasses User"
            : config.participantName;
        return $"{{" +
               $"\"identity\":\"{Escape(_resolvedIdentity)}\"," +
               $"\"room\":\"{Escape(_resolvedRoom)}\"," +
               $"\"name\":\"{Escape(name)}\"," +
               $"\"agent_name\":\"{Escape(config.agentName)}\"" +
               $"}}";
    }

    [Serializable]
    private class TokenResponse
    {
        public string token;
        public string url;
        public string identity;
        public string room;
    }
}
