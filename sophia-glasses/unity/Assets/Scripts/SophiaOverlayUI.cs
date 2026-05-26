using System;
using System.Collections;
using System.Collections.Generic;
using TMPro;
using UnityEngine;
using UnityEngine.UI;

/// <summary>
/// Direction A HUD. Subtitle-minimal, glanceable, peripheral.
///
///   - Top-right:    small colored state dot (no text)
///   - Bottom-center: subtitle showing the latest spoken line, auto-fades
///   - Above the subtitle: vertical stack of RAG source chips, auto-fades
///
/// Central field of view is left clear for the real world. End Session
/// control lives on the Beam Pro screen-space overlay (SessionPicker),
/// not on this world-space canvas.
///
/// Spec: sophia-glasses/HUD_direction_a.md
/// </summary>
public class SophiaOverlayUI : MonoBehaviour
{
    [Header("Canvas placement")]
    [SerializeField] private float distanceFromCamera = 2.0f;
    [SerializeField] private Vector2 canvasSize = new Vector2(1920, 1080);
    [SerializeField] private float canvasScale = 0.0012f;

    [Header("State dot")]
    [SerializeField] private float dotSize = 28f;
    [SerializeField] private float dotEdgeMargin = 48f;
    [SerializeField] private float dotPulseHz = 1.2f;

    [Header("Subtitle")]
    [SerializeField] private int subtitleFontSize = 56;
    [SerializeField] private float subtitleWidth = 1400f;
    [SerializeField] private float subtitleBottomMargin = 80f;
    [SerializeField] private float subtitleHoldAfterSpeak = 2.0f;

    [Header("RAG chips")]
    [SerializeField] private int chipFontSize = 32;
    [SerializeField] private float chipsGap = 60f;
    [SerializeField] private float chipSpacing = 8f;
    [SerializeField] private int maxChips = 6;
    [SerializeField] private float chipsFadeAfterSpeak = 0.5f;

    [Header("Animation")]
    [SerializeField] private float fadeDuration = 0.2f;

    private Canvas _canvas;

    // State dot
    private Image _dotImage;
    private Color _dotBaseColor = new Color(0.5f, 0.5f, 0.5f, 0.9f);
    private string _currentState = "connecting";
    private float _pulsePhase = 0f;

    // Subtitle
    private CanvasGroup _subtitleGroup;
    private RectTransform _subtitleRect;
    private TMP_Text _subtitleText;
    private float _subtitleFadeOutAt = -1f;
    private Coroutine _subtitleFadeCo;

    // RAG chips
    private RectTransform _chipsContainer;
    private CanvasGroup _chipsGroup;
    private float _chipsFadeOutAt = -1f;
    private Coroutine _chipsFadeCo;
    private readonly List<GameObject> _activeChips = new();

    private void OnEnable()
    {
        var cam = Camera.main;
        if (cam == null)
        {
            Debug.LogError("[SophiaOverlayUI] No Camera.main found; tag your " +
                "XREAL/scene camera as MainCamera.");
            return;
        }

        BuildCanvas(cam);
        BuildStateDot();
        BuildSubtitle();
        BuildChipsContainer();

        SetAgentState("connecting");
        _subtitleGroup.alpha = 0f;
        _chipsGroup.alpha = 0f;

        SophiaConnection.OnTextStreamMessage += HandleTextStream;
        Debug.Log("[SophiaOverlayUI] HUD built (Direction A: subtitle-minimal).");
    }

    private void OnDisable()
    {
        SophiaConnection.OnTextStreamMessage -= HandleTextStream;

        if (_canvas != null)
        {
            Destroy(_canvas.gameObject);
            _canvas = null;
        }

        _dotImage = null;
        _subtitleGroup = null;
        _subtitleRect = null;
        _subtitleText = null;
        _chipsContainer = null;
        _chipsGroup = null;
        _activeChips.Clear();
        _subtitleFadeOutAt = -1f;
        _chipsFadeOutAt = -1f;
        _subtitleFadeCo = null;
        _chipsFadeCo = null;
    }

    private void Update()
    {
        // Pulse the state dot while thinking or speaking. Skipped for
        // listening/connecting -- a solid dot is a calm "we're idle and
        // waiting for you" indicator.
        if (_dotImage != null && (_currentState == "thinking" || _currentState == "speaking"))
        {
            _pulsePhase += Time.deltaTime * dotPulseHz * 2f * Mathf.PI;
            float t = 0.5f + 0.5f * Mathf.Sin(_pulsePhase);
            var c = _dotBaseColor;
            c.a = Mathf.Lerp(0.45f, 1.0f, t);
            _dotImage.color = c;
        }

        // Deferred fade-outs. We schedule a real-time deadline rather than
        // starting a coroutine immediately so a new line arriving while the
        // previous one is still on screen extends the visible window.
        if (_subtitleFadeOutAt > 0f && Time.time >= _subtitleFadeOutAt)
        {
            _subtitleFadeOutAt = -1f;
            if (_subtitleFadeCo != null) StopCoroutine(_subtitleFadeCo);
            _subtitleFadeCo = StartCoroutine(FadeTo(_subtitleGroup, 0f));
        }
        if (_chipsFadeOutAt > 0f && Time.time >= _chipsFadeOutAt)
        {
            _chipsFadeOutAt = -1f;
            if (_chipsFadeCo != null) StopCoroutine(_chipsFadeCo);
            _chipsFadeCo = StartCoroutine(FadeTo(_chipsGroup, 0f));
        }
    }

    // ---------- Canvas + element construction ----------

    private void BuildCanvas(Camera cam)
    {
        var canvasGO = new GameObject("SophiaCanvas");
        canvasGO.transform.SetParent(cam.transform, false);
        canvasGO.transform.localPosition = new Vector3(0f, 0f, distanceFromCamera);
        canvasGO.transform.localRotation = Quaternion.identity;
        canvasGO.transform.localScale = Vector3.one * canvasScale;

        _canvas = canvasGO.AddComponent<Canvas>();
        _canvas.renderMode = RenderMode.WorldSpace;
        _canvas.worldCamera = cam;

        var scaler = canvasGO.AddComponent<CanvasScaler>();
        scaler.dynamicPixelsPerUnit = 4f;
        scaler.referencePixelsPerUnit = 100f;

        canvasGO.AddComponent<GraphicRaycaster>();

        var rect = canvasGO.GetComponent<RectTransform>();
        rect.sizeDelta = canvasSize;
        rect.pivot = new Vector2(0.5f, 0.5f);
    }

    private void BuildStateDot()
    {
        var go = new GameObject("StateDot");
        go.transform.SetParent(_canvas.transform, false);

        var rect = go.AddComponent<RectTransform>();
        rect.anchorMin = new Vector2(1f, 1f);
        rect.anchorMax = new Vector2(1f, 1f);
        rect.pivot = new Vector2(1f, 1f);
        rect.anchoredPosition = new Vector2(-dotEdgeMargin, -dotEdgeMargin);
        rect.sizeDelta = new Vector2(dotSize, dotSize);

        _dotImage = go.AddComponent<Image>();
        _dotImage.color = _dotBaseColor;
        _dotImage.sprite = MakeCircleSprite();
        _dotImage.raycastTarget = false;
    }

    private void BuildSubtitle()
    {
        var go = new GameObject("Subtitle");
        go.transform.SetParent(_canvas.transform, false);

        _subtitleRect = go.AddComponent<RectTransform>();
        _subtitleRect.anchorMin = new Vector2(0.5f, 0f);
        _subtitleRect.anchorMax = new Vector2(0.5f, 0f);
        _subtitleRect.pivot = new Vector2(0.5f, 0f);
        _subtitleRect.anchoredPosition = new Vector2(0f, subtitleBottomMargin);
        _subtitleRect.sizeDelta = new Vector2(subtitleWidth, 200f);

        // Translucent near-black background with hairline border via two
        // stacked Images: outer = border color, inner = fill inset by 1 px.
        var border = go.AddComponent<Image>();
        border.color = new Color(1f, 1f, 1f, 0.30f);
        border.raycastTarget = false;

        var fillGO = new GameObject("Fill");
        fillGO.transform.SetParent(go.transform, false);
        var fillRect = fillGO.AddComponent<RectTransform>();
        fillRect.anchorMin = Vector2.zero;
        fillRect.anchorMax = Vector2.one;
        fillRect.offsetMin = new Vector2(1f, 1f);
        fillRect.offsetMax = new Vector2(-1f, -1f);
        var fill = fillGO.AddComponent<Image>();
        fill.color = new Color(0f, 0f, 0f, 0.55f);
        fill.raycastTarget = false;

        var textGO = new GameObject("Text");
        textGO.transform.SetParent(fillGO.transform, false);
        var textRect = textGO.AddComponent<RectTransform>();
        textRect.anchorMin = Vector2.zero;
        textRect.anchorMax = Vector2.one;
        textRect.offsetMin = new Vector2(36f, 24f);
        textRect.offsetMax = new Vector2(-36f, -24f);
        _subtitleText = textGO.AddComponent<TextMeshProUGUI>();
        _subtitleText.text = "";
        _subtitleText.fontSize = subtitleFontSize;
        _subtitleText.alignment = TextAlignmentOptions.MidlineLeft;
        _subtitleText.color = new Color(1f, 1f, 1f, 1f);
        _subtitleText.textWrappingMode = TextWrappingModes.Normal;
        _subtitleText.overflowMode = TextOverflowModes.Ellipsis;
        _subtitleText.maxVisibleLines = 2;

        _subtitleGroup = go.AddComponent<CanvasGroup>();
        _subtitleGroup.alpha = 0f;
        _subtitleGroup.interactable = false;
        _subtitleGroup.blocksRaycasts = false;
    }

    private void BuildChipsContainer()
    {
        var go = new GameObject("RagChips");
        go.transform.SetParent(_canvas.transform, false);

        _chipsContainer = go.AddComponent<RectTransform>();
        _chipsContainer.anchorMin = new Vector2(0.5f, 0f);
        _chipsContainer.anchorMax = new Vector2(0.5f, 0f);
        _chipsContainer.pivot = new Vector2(0.5f, 0f);
        // Sit chipsGap pixels above the top of the subtitle bar.
        _chipsContainer.anchoredPosition = new Vector2(
            0f, subtitleBottomMargin + 200f + chipsGap);
        _chipsContainer.sizeDelta = new Vector2(1200f, 0f); // height grows with children

        var layout = go.AddComponent<VerticalLayoutGroup>();
        layout.childAlignment = TextAnchor.LowerCenter;
        layout.spacing = chipSpacing;
        layout.childForceExpandHeight = false;
        layout.childForceExpandWidth = false;
        layout.childControlHeight = true;
        layout.childControlWidth = true;
        layout.padding = new RectOffset(0, 0, 0, 0);

        var fitter = go.AddComponent<ContentSizeFitter>();
        fitter.verticalFit = ContentSizeFitter.FitMode.PreferredSize;
        fitter.horizontalFit = ContentSizeFitter.FitMode.Unconstrained;

        _chipsGroup = go.AddComponent<CanvasGroup>();
        _chipsGroup.alpha = 0f;
        _chipsGroup.interactable = false;
        _chipsGroup.blocksRaycasts = false;
    }

    private GameObject CreateChip(string label)
    {
        var go = new GameObject("Chip");
        go.transform.SetParent(_chipsContainer, false);

        var le = go.AddComponent<LayoutElement>();
        le.preferredHeight = 56f;
        le.preferredWidth = 800f;

        var border = go.AddComponent<Image>();
        border.color = new Color(1f, 1f, 1f, 0.30f);
        border.raycastTarget = false;

        var fillGO = new GameObject("Fill");
        fillGO.transform.SetParent(go.transform, false);
        var fillRect = fillGO.AddComponent<RectTransform>();
        fillRect.anchorMin = Vector2.zero;
        fillRect.anchorMax = Vector2.one;
        fillRect.offsetMin = new Vector2(1f, 1f);
        fillRect.offsetMax = new Vector2(-1f, -1f);
        var fill = fillGO.AddComponent<Image>();
        fill.color = new Color(0f, 0f, 0f, 0.55f);
        fill.raycastTarget = false;

        var textGO = new GameObject("Text");
        textGO.transform.SetParent(fillGO.transform, false);
        var textRect = textGO.AddComponent<RectTransform>();
        textRect.anchorMin = Vector2.zero;
        textRect.anchorMax = Vector2.one;
        textRect.offsetMin = new Vector2(24f, 6f);
        textRect.offsetMax = new Vector2(-24f, -6f);
        var t = textGO.AddComponent<TextMeshProUGUI>();
        t.text = label;
        t.fontSize = chipFontSize;
        t.alignment = TextAlignmentOptions.Center;
        t.color = new Color(0.92f, 0.95f, 1f, 1f);
        t.textWrappingMode = TextWrappingModes.NoWrap;
        t.overflowMode = TextOverflowModes.Ellipsis;

        return go;
    }

    /// <summary>
    /// A 1x1 white sprite trick that lets Image render as a smooth filled
    /// circle by setting a perfectly square RectTransform and using the
    /// default Sliced sprite. The simplest approach is to use the built-in
    /// UISprite at /Builtin Resources/UI/Knob; failing that, fall back to a
    /// procedurally generated circle texture.
    /// </summary>
    private Sprite MakeCircleSprite()
    {
        const int size = 64;
        var tex = new Texture2D(size, size, TextureFormat.RGBA32, false);
        tex.wrapMode = TextureWrapMode.Clamp;
        tex.filterMode = FilterMode.Bilinear;
        var pixels = new Color[size * size];
        var c0 = new Vector2(size * 0.5f - 0.5f, size * 0.5f - 0.5f);
        float r = size * 0.5f - 1f;
        for (int y = 0; y < size; y++)
        for (int x = 0; x < size; x++)
        {
            float d = Vector2.Distance(new Vector2(x, y), c0);
            float a = Mathf.Clamp01(r - d);
            pixels[y * size + x] = new Color(1f, 1f, 1f, a);
        }
        tex.SetPixels(pixels);
        tex.Apply();
        return Sprite.Create(tex, new Rect(0, 0, size, size),
                              new Vector2(0.5f, 0.5f), 100f);
    }

    // ---------- Text-stream handlers ----------

    private void HandleTextStream(string topic, string fromIdentity, string payload)
    {
        try
        {
            switch (topic)
            {
                case "agent_events":
                    HandleAgentEvent(payload);
                    break;
                case "transcription":
                    HandleTranscription(fromIdentity, payload);
                    break;
                case "rag_result":
                    HandleRagResult(payload);
                    break;
            }
        }
        catch (Exception e)
        {
            Debug.LogWarning($"[SophiaOverlayUI] HandleTextStream({topic}): {e.Message}");
        }
    }

    private void HandleAgentEvent(string payload)
    {
        var kind = ExtractJsonString(payload, "kind");
        if (kind == "agent_state")
        {
            var newState = ExtractJsonString(payload, "new");
            if (string.IsNullOrEmpty(newState)) return;

            string prevState = _currentState;
            SetAgentState(newState);

            // Sophia just finished speaking -- schedule the subtitle and the
            // RAG chips to fade after their respective hold windows.
            if (prevState == "speaking" && newState == "listening")
            {
                _subtitleFadeOutAt = Time.time + subtitleHoldAfterSpeak;
                _chipsFadeOutAt = Time.time + chipsFadeAfterSpeak;
            }
        }
        else if (kind == "user_transcript")
        {
            var text = ExtractJsonString(payload, "text");
            if (!string.IsNullOrEmpty(text)) ShowSubtitle("You", text);
        }
    }

    private void HandleTranscription(string identity, string payload)
    {
        if (string.IsNullOrEmpty(payload)) return;
        bool isAgent = !string.IsNullOrEmpty(identity) && identity.StartsWith("agent-");
        ShowSubtitle(isAgent ? "Sophia" : "You", payload);
    }

    private void HandleRagResult(string payload)
    {
        var mode = ExtractJsonString(payload, "mode");
        if (mode == "retrieve_skipped" || mode == "error")
        {
            // General-chat or failed retrieval -- hide chips entirely.
            ClearChips();
            return;
        }

        var hits = ExtractHits(payload);
        if (hits.Count == 0)
        {
            ClearChips();
            return;
        }

        ShowRagChips(hits);
    }

    // ---------- State + element updates ----------

    private void SetAgentState(string state)
    {
        _currentState = state ?? "connecting";
        _pulsePhase = 0f;

        Color c = state switch
        {
            "listening" => new Color(0.30f, 0.85f, 0.40f, 1f),  // green
            "thinking"  => new Color(0.95f, 0.70f, 0.20f, 1f),  // amber
            "speaking"  => new Color(0.35f, 0.65f, 1.00f, 1f),  // blue
            _           => new Color(0.55f, 0.55f, 0.55f, 0.9f) // grey (connecting / unknown)
        };
        _dotBaseColor = c;
        if (_dotImage != null) _dotImage.color = c;
    }

    private void ShowSubtitle(string speakerLabel, string body)
    {
        if (_subtitleText == null) return;

        // Hex-tint the speaker prefix in TMP rich text so the body stays high
        // contrast white. The body is the substantive part the user actually
        // reads; the prefix is a quiet identifier.
        string prefixColor = speakerLabel == "Sophia" ? "9CC7FF" : "B6E2A1";
        _subtitleText.text =
            $"<color=#{prefixColor}>{speakerLabel}:</color> {body}";

        // Cancel any pending fade-out and snap to fully visible.
        _subtitleFadeOutAt = -1f;
        if (_subtitleFadeCo != null) { StopCoroutine(_subtitleFadeCo); _subtitleFadeCo = null; }
        _subtitleFadeCo = StartCoroutine(FadeTo(_subtitleGroup, 1f));
    }

    private void ShowRagChips(List<(string source, string pageLabel)> hits)
    {
        ClearChips();

        // Dedup by "source p.page", preserving order. Sophia's response may
        // cite multiple pages from the same manual; we keep each unique pair
        // since they're separately useful to a technician.
        var seen = new HashSet<string>();
        foreach (var (source, pageLabel) in hits)
        {
            var label = string.IsNullOrEmpty(pageLabel)
                ? source
                : $"{source}  {pageLabel}";
            if (!seen.Add(label)) continue;

            var chip = CreateChip(label);
            _activeChips.Add(chip);
            if (_activeChips.Count >= maxChips) break;
        }

        _chipsFadeOutAt = -1f;
        if (_chipsFadeCo != null) { StopCoroutine(_chipsFadeCo); _chipsFadeCo = null; }
        _chipsFadeCo = StartCoroutine(FadeTo(_chipsGroup, 1f));
    }

    private void ClearChips()
    {
        foreach (var go in _activeChips)
        {
            if (go != null) Destroy(go);
        }
        _activeChips.Clear();
    }

    private IEnumerator FadeTo(CanvasGroup group, float targetAlpha)
    {
        if (group == null) yield break;
        float start = group.alpha;
        float elapsed = 0f;
        while (elapsed < fadeDuration)
        {
            elapsed += Time.unscaledDeltaTime;
            float t = Mathf.Clamp01(elapsed / fadeDuration);
            // Smoothstep ease-in-out for less mechanical motion.
            float eased = t * t * (3f - 2f * t);
            group.alpha = Mathf.Lerp(start, targetAlpha, eased);
            yield return null;
        }
        group.alpha = targetAlpha;

        // When fully faded out, also clear chips so a stale list doesn't
        // appear when the next session begins.
        if (Mathf.Approximately(targetAlpha, 0f) && group == _chipsGroup)
        {
            ClearChips();
        }
    }

    // ---------- JSON helpers (no Newtonsoft dependency) ----------

    private static string ExtractJsonString(string json, string key)
    {
        if (string.IsNullOrEmpty(json)) return null;
        var keyMarker = "\"" + key + "\":";
        var i = json.IndexOf(keyMarker, StringComparison.Ordinal);
        if (i < 0) return null;
        i += keyMarker.Length;
        while (i < json.Length && (json[i] == ' ' || json[i] == '\t' ||
                                   json[i] == '\n' || json[i] == '\r')) i++;
        if (i >= json.Length || json[i] != '"') return null;
        i++;
        int j = i;
        while (j < json.Length)
        {
            if (json[j] == '\\' && j + 1 < json.Length) { j += 2; continue; }
            if (json[j] == '"') break;
            j++;
        }
        if (j >= json.Length) return null;
        return json.Substring(i, j - i)
            .Replace("\\\"", "\"")
            .Replace("\\n", "\n")
            .Replace("\\\\", "\\");
    }

    /// <summary>
    /// Walk the "hits": [...] array and pull out (source, page-label) for each
    /// hit object. Page is either a number ("page": 35) or a string ("page": "?")
    /// in sophia-spatial-ai's responses; both are accepted and formatted as
    /// "p.X". Hits with no source are skipped.
    /// </summary>
    private static List<(string source, string pageLabel)> ExtractHits(string json)
    {
        var result = new List<(string, string)>();
        if (string.IsNullOrEmpty(json)) return result;

        var hitsKey = "\"hits\":";
        int hitsIdx = json.IndexOf(hitsKey, StringComparison.Ordinal);
        if (hitsIdx < 0) return result;

        int p = hitsIdx + hitsKey.Length;
        while (p < json.Length && json[p] != '[') p++;
        if (p >= json.Length) return result;
        p++; // step past '['

        // Walk objects until the matching ']'. We rely on brace balancing to
        // find object boundaries -- sufficient for the flat hit shape we emit.
        while (p < json.Length)
        {
            while (p < json.Length && (json[p] == ' ' || json[p] == ',' ||
                                       json[p] == '\n' || json[p] == '\r' ||
                                       json[p] == '\t')) p++;
            if (p >= json.Length) break;
            if (json[p] == ']') break;
            if (json[p] != '{') { p++; continue; }

            int depth = 1;
            int start = p;
            p++;
            bool inStr = false;
            while (p < json.Length && depth > 0)
            {
                char ch = json[p];
                if (inStr)
                {
                    if (ch == '\\' && p + 1 < json.Length) { p += 2; continue; }
                    if (ch == '"') inStr = false;
                }
                else
                {
                    if (ch == '"') inStr = true;
                    else if (ch == '{') depth++;
                    else if (ch == '}') depth--;
                }
                p++;
            }
            if (depth != 0) break;

            string obj = json.Substring(start, p - start);
            string source = ExtractJsonString(obj, "source");
            string pageLabel = ExtractPageLabel(obj);
            if (!string.IsNullOrEmpty(source))
            {
                result.Add((source, pageLabel));
            }
        }

        return result;
    }

    private static string ExtractPageLabel(string objJson)
    {
        // Try as raw number first ("page": 35).
        var key = "\"page\":";
        int i = objJson.IndexOf(key, StringComparison.Ordinal);
        if (i < 0) return null;
        i += key.Length;
        while (i < objJson.Length && (objJson[i] == ' ' || objJson[i] == '\t')) i++;
        if (i >= objJson.Length) return null;

        if (objJson[i] == '"')
        {
            // String form -- delegate to the string extractor.
            var s = ExtractJsonString(objJson, "page");
            if (string.IsNullOrEmpty(s) || s == "?") return null;
            return "p." + s;
        }

        int j = i;
        while (j < objJson.Length && (char.IsDigit(objJson[j]) || objJson[j] == '-')) j++;
        if (j == i) return null;
        return "p." + objJson.Substring(i, j - i);
    }
}
