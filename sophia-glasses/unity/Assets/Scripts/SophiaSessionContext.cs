using UnityEngine;

/// <summary>
/// Static state holder for the user's current session choice. Set by
/// SessionPicker when the user taps Start Private or Join Team; read by
/// SophiaConnection.OnEnable when resolving the room name to connect to.
///
/// Why static (not a singleton MonoBehaviour, not a ScriptableObject):
///   - Simplest way to share session-scoped state between SessionPicker
///     and SophiaConnection without scene references, singletons, or DI.
///   - Lives for the app's lifetime (we only have one scene).
///   - Avoids mutating SophiaConfig.asset at runtime, which can leak
///     back to disk in dev builds.
///
/// Usage:
///   // Private mode (auto-generate unique UUID room):
///   SophiaSessionContext.CurrentMode  = SophiaSessionContext.Mode.Private;
///   SophiaSessionContext.RoomOverride = null;
///
///   // Team mode with a typed room code:
///   SophiaSessionContext.CurrentMode  = SophiaSessionContext.Mode.Team;
///   SophiaSessionContext.RoomOverride = "acme/bay-3";
///
///   // End session:
///   SophiaSessionContext.Reset();
///
/// SophiaConnection consumes RoomOverride like this:
///   string desiredRoom = SophiaSessionContext.RoomOverride ?? config.roomName;
///   _resolvedRoom = string.IsNullOrWhiteSpace(desiredRoom)
///       ? $"sophia-glasses-{Guid.NewGuid()...}"
///       : desiredRoom.Trim();
/// </summary>
public static class SophiaSessionContext
{
    public enum Mode { None, Private, Team }

    /// <summary>
    /// Current session mode. None = no active session (picker shown).
    /// Set by SessionPicker before activating the SophiaConnection GameObject.
    /// </summary>
    public static Mode CurrentMode { get; set; } = Mode.None;

    /// <summary>
    /// Room name to use for the next session. Semantics:
    ///   non-null + non-empty -> SophiaConnection uses this verbatim (Team mode)
    ///   null                 -> SophiaConnection falls back to SophiaConfig.roomName
    ///                           which in turn auto-generates a unique UUID room
    ///                           when empty (Private mode default)
    /// </summary>
    public static string RoomOverride { get; set; } = null;

    /// <summary>Clear all session state. Call after the user taps End Session.</summary>
    public static void Reset()
    {
        CurrentMode = Mode.None;
        RoomOverride = null;
    }
}
