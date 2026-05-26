using System;
using TMPro;
using UnityEngine;
using UnityEngine.EventSystems;
using UnityEngine.UI;

/// <summary>
/// Phase 2 picker UI. Shown at app launch and after the user ends a session.
/// Two paths:
///
///   - "Start Private Session"      -> auto-generated unique room (Scenario B)
///   - "Join Team Session" + code   -> shared named room (Scenario A)
///
/// Then an in-session view with an "End Session" button that returns to the
/// picker. Repeatable cycle, no app restart needed.
///
/// Wire-up in Unity Editor:
///   1. SophiaConnection GameObject in the scene must start INACTIVE (uncheck
///      the active checkbox at the top of its Inspector).
///   2. Hierarchy > Create Empty -> rename to "SessionPicker".
///   3. Inspector > Add Component > SessionPicker.
///   4. Drag the SophiaConnection GameObject onto the "Sophia Connection GO"
///      field in the SessionPicker Inspector.
///
/// All UI (Canvas, panels, buttons, input field) is built at runtime in
/// OnEnable -- no Unity Inspector layout work required. Same pattern as
/// SophiaOverlayUI uses for the world-space HUD.
///
/// Architecture: this script doesn't know how SophiaConnection works
/// internally; it just toggles the GameObject active/inactive. SophiaConnection's
/// existing OnEnable / OnDisable lifecycle does all the heavy lifting
/// (connect/disconnect, mic publish/stop, HUD build/teardown).
/// </summary>
public class SessionPicker : MonoBehaviour
{
    [Header("Required")]
    [Tooltip("The SophiaConnection GameObject in the scene. Drag from " +
             "Hierarchy. This script toggles it active/inactive to start " +
             "and end sessions.")]
    [SerializeField] private GameObject sophiaConnectionGO;

    // Runtime-built UI references
    private Canvas _canvas;
    private GameObject _pickerPanel;
    private GameObject _inSessionPanel;
    private TMP_InputField _roomCodeInput;
    private TMP_Text _sessionLabel;

    // -------------------------------------------------------------------------
    // Lifecycle
    // -------------------------------------------------------------------------

    private void OnEnable()
    {
        if (sophiaConnectionGO == null)
        {
            Debug.LogError("[SessionPicker] sophiaConnectionGO is not " +
                "assigned. Drag the SophiaConnection GameObject onto this " +
                "field in the Inspector.");
            return;
        }

        // Safety: make sure SophiaConnection starts inactive so the picker
        // gets first crack at the user. (Belt-and-suspenders -- the user
        // should have unchecked it in the Hierarchy too.)
        if (sophiaConnectionGO.activeSelf)
        {
            Debug.LogWarning("[SessionPicker] SophiaConnection GameObject " +
                "was active at picker startup. Deactivating so the picker " +
                "shows first. Uncheck its active checkbox in the Hierarchy " +
                "to suppress this warning on next run.");
            sophiaConnectionGO.SetActive(false);
        }

        EnsureEventSystem();
        BuildCanvas();
        BuildPickerPanel();
        BuildInSessionPanel();
        ShowPicker();

        Debug.Log("[SessionPicker] Picker UI built and shown.");
    }

    private void OnDisable()
    {
        if (_canvas != null)
        {
            Destroy(_canvas.gameObject);
            _canvas = null;
        }
        _pickerPanel = null;
        _inSessionPanel = null;
        _roomCodeInput = null;
        _sessionLabel = null;
    }

    // -------------------------------------------------------------------------
    // Button handlers
    // -------------------------------------------------------------------------

    public void OnStartPrivate()
    {
        SophiaSessionContext.CurrentMode = SophiaSessionContext.Mode.Private;
        SophiaSessionContext.RoomOverride = null;  // null -> SophiaConnection auto-generates UUID
        Debug.Log("[SessionPicker] User started Private session.");
        StartSession("private");
    }

    public void OnJoinTeam()
    {
        var code = _roomCodeInput != null ? _roomCodeInput.text?.Trim() : null;
        if (string.IsNullOrWhiteSpace(code))
        {
            Debug.LogWarning("[SessionPicker] Join Team tapped with empty room code; ignoring.");
            return;
        }
        SophiaSessionContext.CurrentMode = SophiaSessionContext.Mode.Team;
        SophiaSessionContext.RoomOverride = code;
        Debug.Log($"[SessionPicker] User joined Team session: '{code}'.");
        StartSession(code);
    }

    public void OnEndSession()
    {
        Debug.Log("[SessionPicker] User ended session.");
        // SetActive(false) on SophiaConnection fires its OnDisable -> Cleanup()
        // -> mic stop + room disconnect. SophiaOverlayUI on the same GameObject
        // also gets OnDisable -> destroys the world-space HUD canvas.
        sophiaConnectionGO.SetActive(false);
        SophiaSessionContext.Reset();
        ShowPicker();
    }

    public void OnQuit()
    {
        Debug.Log("[SessionPicker] User quit app.");
        // SophiaConnection's OnApplicationQuit also fires; redundant but safe.
        sophiaConnectionGO.SetActive(false);
        Application.Quit();
    }

    // -------------------------------------------------------------------------
    // State transitions
    // -------------------------------------------------------------------------

    private void StartSession(string roomLabel)
    {
        if (_sessionLabel != null)
        {
            // For Private mode, roomLabel == "private" but SophiaConnection
            // will generate the actual UUID. Show a friendly placeholder
            // since we don't know the UUID yet at this point.
            _sessionLabel.text = SophiaSessionContext.CurrentMode == SophiaSessionContext.Mode.Private
                ? "Session: (private, just you)"
                : $"Session: {roomLabel}";
        }
        if (_pickerPanel != null) _pickerPanel.SetActive(false);
        if (_inSessionPanel != null) _inSessionPanel.SetActive(true);
        sophiaConnectionGO.SetActive(true);  // -> SophiaConnection.OnEnable -> ConnectFlow
    }

    private void ShowPicker()
    {
        if (_pickerPanel != null) _pickerPanel.SetActive(true);
        if (_inSessionPanel != null) _inSessionPanel.SetActive(false);
        // Reset the input field so the user starts fresh on next Team attempt.
        if (_roomCodeInput != null) _roomCodeInput.text = "";
    }

    // -------------------------------------------------------------------------
    // UI construction (runtime, no Inspector wiring required)
    // -------------------------------------------------------------------------

    /// <summary>
    /// Unity UI buttons require an EventSystem GameObject in the scene to
    /// receive any clicks. Normally Unity auto-creates one when you add a
    /// UI element via the Hierarchy menu -- but since we build the Canvas
    /// entirely in code, no auto-create fires. Without an EventSystem,
    /// buttons render and look interactive but no click ever fires.
    /// Self-heal by creating one if missing.
    ///
    /// Unity 6 URP template defaults to the New Input System (only) — in
    /// that mode StandaloneInputModule does nothing and clicks are silently
    /// dropped. Try InputSystemUIInputModule first (loaded via reflection so
    /// this code compiles even if the Input System package isn't installed),
    /// fall back to StandaloneInputModule for legacy / "Both" projects.
    /// </summary>
    private void EnsureEventSystem()
    {
        if (EventSystem.current != null)
        {
            Debug.Log("[SessionPicker] EventSystem already exists, reusing.");
            return;
        }
        var es = new GameObject("EventSystem");
        es.AddComponent<EventSystem>();

        var newInputType = System.Type.GetType(
            "UnityEngine.InputSystem.UI.InputSystemUIInputModule, Unity.InputSystem");
        if (newInputType != null)
        {
            es.AddComponent(newInputType);
            Debug.Log("[SessionPicker] EventSystem created with InputSystemUIInputModule (New Input System).");
        }
        else
        {
            es.AddComponent<StandaloneInputModule>();
            Debug.Log("[SessionPicker] EventSystem created with StandaloneInputModule (legacy input).");
        }
    }

    private void BuildCanvas()
    {
        var canvasGO = new GameObject("SessionPickerCanvas");
        canvasGO.transform.SetParent(transform, false);

        _canvas = canvasGO.AddComponent<Canvas>();
        _canvas.renderMode = RenderMode.ScreenSpaceOverlay;
        // High sort order so we render on top of any other UI (e.g. the HUD
        // canvas from SophiaOverlayUI, which is world-space at a lower order).
        _canvas.sortingOrder = 100;

        var scaler = canvasGO.AddComponent<CanvasScaler>();
        scaler.uiScaleMode = CanvasScaler.ScaleMode.ScaleWithScreenSize;
        // XREAL One Pro is 1920x1080 landscape per eye; Beam Pro renders the
        // Android surface in landscape and projects stereo. Reference must be
        // landscape, otherwise the card gets clipped top/bottom in glasses.
        scaler.referenceResolution = new Vector2(1920, 1080);
        scaler.screenMatchMode = CanvasScaler.ScreenMatchMode.MatchWidthOrHeight;
        scaler.matchWidthOrHeight = 0.5f;

        canvasGO.AddComponent<GraphicRaycaster>();
    }

    private void BuildPickerPanel()
    {
        _pickerPanel = new GameObject("PickerPanel");
        _pickerPanel.transform.SetParent(_canvas.transform, false);
        var rect = _pickerPanel.AddComponent<RectTransform>();
        rect.anchorMin = Vector2.zero;
        rect.anchorMax = Vector2.one;
        rect.offsetMin = Vector2.zero;
        rect.offsetMax = Vector2.zero;
        var bg = _pickerPanel.AddComponent<Image>();
        bg.color = new Color(0.03f, 0.05f, 0.10f, 0.95f);  // near-opaque dark backdrop

        // Landscape card (1500x900) fits comfortably inside a 1920x1080 frame
        // with breathing room on all sides. Two-column body: Private on left,
        // Team on right, separated by a vertical divider.
        var card = CreateChild(_pickerPanel, "Card", new Vector2(0.5f, 0.5f),
                               new Vector2(0.5f, 0.5f), new Vector2(0f, 0f),
                               new Vector2(1500f, 900f));
        var cardImg = card.AddComponent<Image>();
        cardImg.color = new Color(0.07f, 0.10f, 0.18f, 1f);

        // Title + subtitle (top, centered, spans full card width)
        AddText(card, "Sophia", 96, FontStyles.Bold,
                new Vector2(0.5f, 1f), new Vector2(0.5f, 1f), new Vector2(0f, -40f),
                new Vector2(1400f, 110f), new Color(0.91f, 0.93f, 0.96f, 1f),
                TextAlignmentOptions.Center);

        AddText(card, "Voice agent for industrial manuals", 32, FontStyles.Normal,
                new Vector2(0.5f, 1f), new Vector2(0.5f, 1f), new Vector2(0f, -160f),
                new Vector2(1400f, 50f), new Color(0.7f, 0.74f, 0.82f, 1f),
                TextAlignmentOptions.Center);

        // Vertical divider down the middle of the body
        var divider = CreateChild(card, "Divider",
                                   new Vector2(0.5f, 0.5f), new Vector2(0.5f, 0.5f),
                                   new Vector2(0f, -80f), new Vector2(2f, 540f));
        divider.AddComponent<Image>().color = new Color(0.2f, 0.25f, 0.35f, 1f);

        // Left column: Private session (anchored to left-middle of card)
        var privSection = CreateChild(card, "PrivateSection",
                                      new Vector2(0f, 0.5f), new Vector2(0f, 0.5f),
                                      new Vector2(40f, -80f), new Vector2(680f, 540f));

        AddText(privSection, "Just you and Sophia", 32, FontStyles.Italic,
                new Vector2(0.5f, 1f), new Vector2(0.5f, 1f), new Vector2(0f, -20f),
                new Vector2(660f, 50f), new Color(0.6f, 0.65f, 0.74f, 1f),
                TextAlignmentOptions.Center);

        BuildButton(privSection, "Start Private Session",
                    new Vector2(0.5f, 0.5f), new Vector2(0.5f, 0.5f),
                    new Vector2(0f, -20f), new Vector2(600f, 180f),
                    new Color(0.15f, 0.55f, 0.25f, 1f),
                    OnStartPrivate, fontSize: 44, bold: true);

        // Right column: Team session (anchored to right-middle of card)
        var teamSection = CreateChild(card, "TeamSection",
                                      new Vector2(1f, 0.5f), new Vector2(1f, 0.5f),
                                      new Vector2(-40f, -80f), new Vector2(680f, 540f));

        AddText(teamSection, "Join an existing team room", 32, FontStyles.Italic,
                new Vector2(0.5f, 1f), new Vector2(0.5f, 1f), new Vector2(0f, -20f),
                new Vector2(660f, 50f), new Color(0.6f, 0.65f, 0.74f, 1f),
                TextAlignmentOptions.Center);

        BuildInputField(teamSection,
                        new Vector2(0.5f, 0.5f), new Vector2(0.5f, 0.5f),
                        new Vector2(0f, 60f), new Vector2(600f, 100f),
                        placeholder: "Enter room code (e.g. acme/bay-3)");

        BuildButton(teamSection, "Join Team Session",
                    new Vector2(0.5f, 0.5f), new Vector2(0.5f, 0.5f),
                    new Vector2(0f, -90f), new Vector2(600f, 130f),
                    new Color(0.15f, 0.4f, 0.7f, 1f),
                    OnJoinTeam, fontSize: 40, bold: true);

        // Quit button (small, bottom-center of card)
        BuildButton(card, "Quit App",
                    new Vector2(0.5f, 0f), new Vector2(0.5f, 0f),
                    new Vector2(0f, 30f), new Vector2(300f, 60f),
                    new Color(0.3f, 0.3f, 0.35f, 1f),
                    OnQuit, fontSize: 28, bold: false);
    }

    private void BuildInSessionPanel()
    {
        // Direction A: minimize the in-session controls so they don't compete
        // with the world-space HUD that lives inside the XREAL field of view.
        // What used to be a 900x130 bottom-center strip with a session label
        // and a full-width "End Session" button is now a small corner chip
        // anchored to the bottom-right of the Beam Pro screen overlay. The
        // chip sits at the very edge of XREAL One Pro's comfortable FOV so
        // it's effectively invisible in glasses while still being tappable on
        // the phone touchscreen. The session label is gone -- mode is implied
        // by the picker the user just came from, and the world-space state
        // dot already signals that a session is live.
        _inSessionPanel = new GameObject("InSessionPanel");
        _inSessionPanel.transform.SetParent(_canvas.transform, false);
        var rect = _inSessionPanel.AddComponent<RectTransform>();
        rect.anchorMin = new Vector2(1f, 0f);
        rect.anchorMax = new Vector2(1f, 0f);
        rect.pivot     = new Vector2(1f, 0f);
        rect.anchoredPosition = new Vector2(-32f, 32f);
        rect.sizeDelta = new Vector2(120f, 80f);

        // The InSessionPanel itself has no background; the End chip below
        // carries the entire visual footprint.
        // _sessionLabel left as null on purpose; StartSession() null-checks it.
        _sessionLabel = null;

        BuildButton(_inSessionPanel, "End",
                    new Vector2(0.5f, 0.5f), new Vector2(0.5f, 0.5f),
                    new Vector2(0f, 0f), new Vector2(120f, 80f),
                    new Color(0.55f, 0.18f, 0.18f, 0.85f),
                    OnEndSession, fontSize: 30, bold: true);
    }

    // -------------------------------------------------------------------------
    // Construction helpers
    // -------------------------------------------------------------------------

    private GameObject CreateChild(GameObject parent, string name, Vector2 anchor,
                                   Vector2 pivot, Vector2 offset, Vector2 size)
    {
        var go = new GameObject(name);
        go.transform.SetParent(parent.transform, false);
        var rect = go.AddComponent<RectTransform>();
        rect.anchorMin = anchor;
        rect.anchorMax = anchor;
        rect.pivot = pivot;
        rect.anchoredPosition = offset;
        rect.sizeDelta = size;
        return go;
    }

    private TMP_Text AddText(GameObject parent, string text, int fontSize,
                             FontStyles style, Vector2 anchorMin, Vector2 anchorMax,
                             Vector2 offset, Vector2 size, Color color,
                             TextAlignmentOptions alignment)
    {
        var go = new GameObject("Text");
        go.transform.SetParent(parent.transform, false);
        var rect = go.AddComponent<RectTransform>();
        rect.anchorMin = anchorMin;
        rect.anchorMax = anchorMax;
        rect.pivot = anchorMin;  // assume pivot at anchor
        rect.anchoredPosition = offset;
        rect.sizeDelta = size;
        var t = go.AddComponent<TextMeshProUGUI>();
        t.text = text;
        t.fontSize = fontSize;
        t.fontStyle = style;
        t.color = color;
        t.alignment = alignment;
        t.textWrappingMode = TextWrappingModes.Normal;
        t.overflowMode = TextOverflowModes.Ellipsis;
        return t;
    }

    private void BuildButton(GameObject parent, string label, Vector2 anchorMin,
                             Vector2 anchorMax, Vector2 offset, Vector2 size,
                             Color bgColor, Action onClick, int fontSize, bool bold)
    {
        var go = new GameObject(label);
        go.transform.SetParent(parent.transform, false);
        var rect = go.AddComponent<RectTransform>();
        rect.anchorMin = anchorMin;
        rect.anchorMax = anchorMax;
        rect.pivot = new Vector2(0.5f, 0.5f);
        rect.anchoredPosition = offset;
        rect.sizeDelta = size;

        var img = go.AddComponent<Image>();
        img.color = bgColor;

        var btn = go.AddComponent<Button>();
        btn.targetGraphic = img;
        // Stronger contrast on press so the user sees the tap registered
        // immediately, before the click handler effects kick in.
        var colors = btn.colors;
        colors.normalColor = Color.white;
        colors.highlightedColor = new Color(0.82f, 0.82f, 0.82f, 1f);
        colors.pressedColor = new Color(0.55f, 0.55f, 0.55f, 1f);
        colors.selectedColor = new Color(0.92f, 0.92f, 0.92f, 1f);
        colors.disabledColor = new Color(0.5f, 0.5f, 0.5f, 0.5f);
        colors.fadeDuration = 0.05f;
        btn.colors = colors;
        btn.onClick.AddListener(() => {
            Debug.Log($"[SessionPicker] Button tapped: {label}");
            onClick?.Invoke();
        });

        // Label
        var lblGO = new GameObject("Label");
        lblGO.transform.SetParent(go.transform, false);
        var lblRect = lblGO.AddComponent<RectTransform>();
        lblRect.anchorMin = Vector2.zero;
        lblRect.anchorMax = Vector2.one;
        lblRect.offsetMin = new Vector2(16f, 8f);
        lblRect.offsetMax = new Vector2(-16f, -8f);
        var lbl = lblGO.AddComponent<TextMeshProUGUI>();
        lbl.text = label;
        lbl.fontSize = fontSize;
        lbl.alignment = TextAlignmentOptions.Center;
        lbl.color = Color.white;
        lbl.textWrappingMode = TextWrappingModes.NoWrap;
        lbl.overflowMode = TextOverflowModes.Ellipsis;
        if (bold) lbl.fontStyle = FontStyles.Bold;
    }

    private void BuildInputField(GameObject parent, Vector2 anchorMin, Vector2 anchorMax,
                                 Vector2 offset, Vector2 size, string placeholder)
    {
        var go = new GameObject("RoomCodeInput");
        go.transform.SetParent(parent.transform, false);
        var rect = go.AddComponent<RectTransform>();
        rect.anchorMin = anchorMin;
        rect.anchorMax = anchorMax;
        rect.pivot = new Vector2(0.5f, 0.5f);
        rect.anchoredPosition = offset;
        rect.sizeDelta = size;

        var img = go.AddComponent<Image>();
        img.color = new Color(0.13f, 0.17f, 0.25f, 1f);

        // Text Area (required child for TMP_InputField)
        var textArea = new GameObject("Text Area");
        textArea.transform.SetParent(go.transform, false);
        var taRect = textArea.AddComponent<RectTransform>();
        taRect.anchorMin = Vector2.zero;
        taRect.anchorMax = Vector2.one;
        taRect.offsetMin = new Vector2(20f, 10f);
        taRect.offsetMax = new Vector2(-20f, -10f);
        textArea.AddComponent<RectMask2D>();

        // Placeholder
        var placeholderGO = new GameObject("Placeholder");
        placeholderGO.transform.SetParent(textArea.transform, false);
        var phRect = placeholderGO.AddComponent<RectTransform>();
        phRect.anchorMin = Vector2.zero;
        phRect.anchorMax = Vector2.one;
        phRect.offsetMin = Vector2.zero;
        phRect.offsetMax = Vector2.zero;
        var phText = placeholderGO.AddComponent<TextMeshProUGUI>();
        phText.text = placeholder;
        phText.fontSize = 32;
        phText.color = new Color(0.5f, 0.55f, 0.62f, 1f);
        phText.fontStyle = FontStyles.Italic;
        phText.alignment = TextAlignmentOptions.Left;

        // Actual input text
        var textGO = new GameObject("Text");
        textGO.transform.SetParent(textArea.transform, false);
        var txRect = textGO.AddComponent<RectTransform>();
        txRect.anchorMin = Vector2.zero;
        txRect.anchorMax = Vector2.one;
        txRect.offsetMin = Vector2.zero;
        txRect.offsetMax = Vector2.zero;
        var tx = textGO.AddComponent<TextMeshProUGUI>();
        tx.fontSize = 36;
        tx.color = new Color(0.95f, 0.97f, 1f, 1f);
        tx.alignment = TextAlignmentOptions.Left;

        // Wire up the input field
        _roomCodeInput = go.AddComponent<TMP_InputField>();
        _roomCodeInput.textViewport = taRect;
        _roomCodeInput.textComponent = tx;
        _roomCodeInput.placeholder = phText;
        _roomCodeInput.lineType = TMP_InputField.LineType.SingleLine;
        _roomCodeInput.characterLimit = 80;
    }
}
