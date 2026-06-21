import json
import math
import time
from collections import deque
from pathlib import Path

import cv2
import mediapipe as mp
import numpy as np
import pyautogui
import tkinter as tk

# Disable the default 0.1 s post-call delay — without this every pyautogui
# call stalls the webcam loop by 100 ms, killing responsiveness.
pyautogui.PAUSE = 0

mp_hands = mp.solutions.hands
HL = mp_hands.HandLandmark        # Short alias used throughout for readability

HAND_CONNECTIONS = list(mp_hands.HAND_CONNECTIONS)

_ROTATION_MAP = {
    "none": None,
    "cw":  cv2.ROTATE_90_CLOCKWISE,           # 90° right
    "ccw": cv2.ROTATE_90_COUNTERCLOCKWISE,    # 90° left
    "180": cv2.ROTATE_180,
}

# Pose name constants — the only strings used for pose identity
POSE_NONE        = "NONE"
POSE_FIST        = "FIST"
POSE_PINCH       = "PINCH"
POSE_TWO_FINGER  = "TWO_FINGER"
POSE_FOUR_FINGER = "FOUR_FINGER"
POSE_OPEN_HAND   = "OPEN_HAND"

# Config key defaults — merged over whatever is in config.json
_CONFIG_DEFAULTS = {
    "camera_index": 0,
    "rotation": "none",
    # Pose classification
    "fist_curl_fingers":   3,      # Min non-thumb curled fingers to trigger FIST; raise if triggering too easily
    "pinch_threshold":     0.35,   # Normalized thumb-index gap; lower = pinch requires fingers closer together
    # PINCH action
    "pinch_key":           "l",    # Key pressed on pinch; change to any single key string
    "like_key_cooldown":   1.0,    # Seconds between pinch presses; raise to prevent accidental repeats
    # TWO_FINGER scroll
    "axis_lock_threshold": 0.04,   # Accumulated displacement before axis locks; lower = locks faster on diagonal swipes
    "scroll_sensitivity":  150,    # Scroll amount per unit of hand travel; raise = faster scroll, lower = heavier/slower
    # FOUR_FINGER tab switch
    "tab_swipe_velocity":  2.0,    # Normalized-widths/sec to trigger tab switch; lower = more sensitive to slow swipes
    "tab_swipe_cooldown":  0.5,    # Seconds between tab switches; lower allows faster repeated switching
    # OPEN_HAND Alt-Tab
    "app_swipe_velocity":  2.0,    # Same velocity threshold for Alt-Tab step; lower = more sensitive
    "app_swipe_cooldown":  0.5,    # Seconds between Alt-Tab steps; lower allows faster stepping
    "alt_release_timeout": 4.0,    # Max seconds Alt stays held without OPEN_HAND; lower = safer faster release
    # FIST app switch (one-shot quick Alt+Tab)
    "fist_swipe_velocity": 2.0,    # Normalized-widths/sec for fist swipe; lower = triggers on slower swipe
    "fist_swipe_cooldown": 0.6,    # Seconds between fist switches; raise if one swipe fires twice
}


def load_config():
    config_path = Path(__file__).with_name("config.json")
    if not config_path.exists():
        return dict(_CONFIG_DEFAULTS)
    with config_path.open(encoding="utf-8") as f:
        data = json.load(f)
    return {**_CONFIG_DEFAULTS, **data}


def overlay_size(rotation):
    # Portrait when rotated 90°; landscape when not.
    if rotation in ("cw", "ccw"):
        return 180, 240
    return 240, 180


# Transparent color key — pixels this color become see-through
_TRANSPARENT_KEY = "black"

HAND_HEX = "#00FF88"   # green skeleton (Tkinter overlay)
HAND_BGR = (136, 255, 0)  # green skeleton (OpenCV frame)


# ---------------------------------------------------------------------------
# Floating overlay window (unchanged from baseline)
# ---------------------------------------------------------------------------

class SkeletonOverlay:
    """Small always-on-top floating window that draws the hand skeleton(s)."""

    def __init__(self, width, height):
        self._width = width
        self._height = height

        self._root = tk.Tk()
        self._root.withdraw()           # hide the invisible root window

        self._win = tk.Toplevel(self._root)
        self._win.title("Hand Overlay")
        self._win.geometry(f"{width}x{height}+40+40")
        self._win.resizable(False, False)
        self._win.overrideredirect(True)    # borderless / no title bar
        self._win.wm_attributes("-topmost", True)

        try:
            self._win.wm_attributes("-transparentcolor", _TRANSPARENT_KEY)
        except tk.TclError:
            pass

        self._canvas = tk.Canvas(
            self._win,
            width=width, height=height,
            bg=_TRANSPARENT_KEY,
            highlightthickness=0,
        )
        self._canvas.pack(fill="both", expand=True)

        self._drag_start_x = 0
        self._drag_start_y = 0
        self._canvas.bind("<ButtonPress-1>", self._on_drag_start)
        self._canvas.bind("<B1-Motion>", self._on_drag_motion)

        close_btn = tk.Label(
            self._win, text="×", fg="#888888", bg=_TRANSPARENT_KEY,
            font=("Helvetica", 14, "bold"), cursor="hand2",
        )
        close_btn.place(relx=1.0, rely=0.0, x=-4, y=2, anchor="ne")
        close_btn.bind("<ButtonPress-1>", lambda _e: self.hide())

        self._hands = []
        self._visible = True
        self._quit_requested = False

        self._win.bind("<KeyPress-q>", lambda _e: self._request_quit())
        self._win.bind("<KeyPress-Q>", lambda _e: self._request_quit())
        self._win.bind("<Escape>", lambda _e: self._request_quit())

    def _request_quit(self):
        self._quit_requested = True

    def quit_requested(self):
        return self._quit_requested

    def _on_drag_start(self, event):
        self._drag_start_x = event.x_root - self._win.winfo_x()
        self._drag_start_y = event.y_root - self._win.winfo_y()

    def _on_drag_motion(self, event):
        x = event.x_root - self._drag_start_x
        y = event.y_root - self._drag_start_y
        self._win.geometry(f"+{x}+{y}")

    def set_hands(self, hands):
        """Pass a list of (landmarks, color_hex) tuples to draw this frame."""
        self._hands = hands or []

    def refresh(self):
        self._canvas.delete("all")
        for landmarks, color in self._hands:
            self._draw_skeleton(landmarks, color)
        # update_idletasks() instead of update(): the venv's Python 3.9
        # Apple system Tk busy-loops forever inside update() on macOS.
        self._root.update_idletasks()

    def show(self):
        if not self._visible:
            self._win.deiconify()
            self._visible = True

    def hide(self):
        if self._visible:
            self._win.withdraw()
            self._visible = False

    def toggle(self):
        if self._visible:
            self.hide()
        else:
            self.show()

    def is_visible(self):
        return self._visible

    def destroy(self):
        try:
            self._root.destroy()
        except Exception:
            pass

    def _draw_skeleton(self, landmarks, color):
        w, h = self._width, self._height

        for a, b in HAND_CONNECTIONS:
            lm_a = landmarks.landmark[a]
            lm_b = landmarks.landmark[b]
            x1, y1 = int(lm_a.x * w), int(lm_a.y * h)
            x2, y2 = int(lm_b.x * w), int(lm_b.y * h)
            self._canvas.create_line(x1, y1, x2, y2, fill="#003080",
                                     width=9, capstyle=tk.ROUND)

        for a, b in HAND_CONNECTIONS:
            lm_a = landmarks.landmark[a]
            lm_b = landmarks.landmark[b]
            x1, y1 = int(lm_a.x * w), int(lm_a.y * h)
            x2, y2 = int(lm_b.x * w), int(lm_b.y * h)
            self._canvas.create_line(x1, y1, x2, y2, fill=color,
                                     width=2, capstyle=tk.ROUND)

        for lm in landmarks.landmark:
            cx, cy = int(lm.x * w), int(lm.y * h)
            r = 5
            self._canvas.create_oval(cx - r, cy - r, cx + r, cy + r,
                                     fill="white", outline=color, width=1)


# ---------------------------------------------------------------------------
# Skeleton + hint drawing on the main camera window (unchanged from baseline)
# ---------------------------------------------------------------------------

def draw_glowing_hand(frame, hand_landmarks, w, h, color=HAND_BGR):
    glow = frame.copy()
    for connection in HAND_CONNECTIONS:
        start = hand_landmarks.landmark[connection[0]]
        end   = hand_landmarks.landmark[connection[1]]
        x1, y1 = int(start.x * w), int(start.y * h)
        x2, y2 = int(end.x   * w), int(end.y   * h)
        cv2.line(glow, (x1, y1), (x2, y2), color, 12)
    cv2.addWeighted(glow, 0.35, frame, 0.65, 0, frame)

    for connection in HAND_CONNECTIONS:
        start = hand_landmarks.landmark[connection[0]]
        end   = hand_landmarks.landmark[connection[1]]
        x1, y1 = int(start.x * w), int(start.y * h)
        x2, y2 = int(end.x   * w), int(end.y   * h)
        cv2.line(frame, (x1, y1), (x2, y2), color, 2)

    for lm in hand_landmarks.landmark:
        cx, cy = int(lm.x * w), int(lm.y * h)
        cv2.circle(frame, (cx, cy), 6, (255, 255, 255), -1)
        cv2.circle(frame, (cx, cy), 8, color, 1)


def draw_hint(frame, w, h):
    cv2.putText(frame, "Q=quit  F=fullscreen  H=hide cam  O=overlay",
                (10, h - 12), cv2.FONT_HERSHEY_SIMPLEX, 0.4,
                (90, 90, 90), 1, cv2.LINE_AA)


def draw_debug(frame, debug_lines, h):
    """Draw gesture debug info in the top-left corner of the camera feed."""
    for i, line in enumerate(debug_lines):
        y = 20 + i * 18
        # Dark shadow for legibility on any background
        cv2.putText(frame, line, (9, y + 1), cv2.FONT_HERSHEY_SIMPLEX,
                    0.5, (0, 0, 0), 2, cv2.LINE_AA)
        cv2.putText(frame, line, (9, y), cv2.FONT_HERSHEY_SIMPLEX,
                    0.5, (0, 255, 136), 1, cv2.LINE_AA)


# ---------------------------------------------------------------------------
# Landmark distance helpers
# ---------------------------------------------------------------------------

def _lm_dist(landmarks, a, b):
    """Euclidean distance between two landmarks in normalized (0–1) coords."""
    la = landmarks.landmark[a]
    lb = landmarks.landmark[b]
    return math.hypot(la.x - lb.x, la.y - lb.y)


def _is_finger_curled(landmarks, tip, mcp):
    """
    A non-thumb finger is 'curled' when its TIP is closer to the WRIST than
    its own MCP knuckle is.  This is rotation-independent and works regardless
    of hand orientation in the frame.
    """
    dist_tip = _lm_dist(landmarks, tip, HL.WRIST)
    dist_mcp = _lm_dist(landmarks, mcp, HL.WRIST)
    return dist_tip < dist_mcp


def _is_thumb_extended(landmarks):
    """
    Thumb is 'extended' when THUMB_TIP is farther from WRIST than THUMB_MCP.
    NOTE: This is the LEAST RELIABLE of the five — the thumb doesn't curl into
    the palm as cleanly as the other fingers and likely needs the most tuning.
    If you get false positives on FOUR_FINGER vs OPEN_HAND, start here.
    """
    return _lm_dist(landmarks, HL.THUMB_TIP, HL.WRIST) > \
           _lm_dist(landmarks, HL.THUMB_MCP, HL.WRIST)


# ---------------------------------------------------------------------------
# Pose classifier
# ---------------------------------------------------------------------------

def classify_pose(landmarks, config):
    """
    Return exactly one pose constant for the given hand landmarks.

    Priority (highest → lowest):
        FIST > PINCH > TWO_FINGER > FOUR_FINGER > OPEN_HAND > NONE
    """
    # --- Curl / extension state for each finger ---
    index_curled  = _is_finger_curled(landmarks, HL.INDEX_FINGER_TIP,  HL.INDEX_FINGER_MCP)
    middle_curled = _is_finger_curled(landmarks, HL.MIDDLE_FINGER_TIP, HL.MIDDLE_FINGER_MCP)
    ring_curled   = _is_finger_curled(landmarks, HL.RING_FINGER_TIP,   HL.RING_FINGER_MCP)
    pinky_curled  = _is_finger_curled(landmarks, HL.PINKY_TIP,         HL.PINKY_MCP)
    thumb_ext     = _is_thumb_extended(landmarks)

    # FIST — at least fist_curl_fingers of the 4 non-thumb fingers are curled.
    # Raise fist_curl_fingers (max 4) if loose fists trigger it; lower it if it
    # won't trigger with a full fist.
    curl_count = sum([index_curled, middle_curled, ring_curled, pinky_curled])
    if curl_count >= config["fist_curl_fingers"]:
        return POSE_FIST

    # PINCH — normalized thumb-to-index-tip gap below threshold.
    # hand_scale normalises for distance-to-camera so the threshold is stable.
    # Lower pinch_threshold = pinch must be tighter; raise it if it won't trigger.
    hand_scale = _lm_dist(landmarks, HL.WRIST, HL.MIDDLE_FINGER_MCP)
    if hand_scale > 1e-6:
        pinch_dist = _lm_dist(landmarks, HL.THUMB_TIP, HL.INDEX_FINGER_TIP) / hand_scale
        if pinch_dist < config["pinch_threshold"]:
            return POSE_PINCH

    # TWO_FINGER — index + middle extended, ring + pinky curled (thumb ignored).
    if (not index_curled) and (not middle_curled) and ring_curled and pinky_curled:
        return POSE_TWO_FINGER

    # FOUR_FINGER — four fingers all extended, thumb tucked in.
    # (Thumb state checked so an open hand doesn't accidentally tab-switch.)
    if (not index_curled) and (not middle_curled) and \
       (not ring_curled)  and (not pinky_curled) and (not thumb_ext):
        return POSE_FOUR_FINGER

    # OPEN_HAND — all five fingers extended, including thumb.
    if (not index_curled) and (not middle_curled) and \
       (not ring_curled)  and (not pinky_curled) and thumb_ext:
        return POSE_OPEN_HAND

    return POSE_NONE


# ---------------------------------------------------------------------------
# Gesture state machine
# ---------------------------------------------------------------------------

class GestureController:
    """
    Centralised state machine that tracks active pose, per-pose motion data,
    and Alt-held status.

    ALL pose-transition logic lives here so the Alt-release safety requirement
    for the OPEN_HAND gesture can never be skipped by a code path that bypasses
    this class.
    """

    _BUFFER_SIZE  = 4   # Rolling window of raw pose frames for smoothing
    _AGREE_NEEDED = 3   # Frames in window that must agree before pose changes

    def __init__(self, config):
        self._cfg = config

        # Temporal smoothing — pre-filled with NONE so the first real frames
        # don't immediately promote an unconfirmed pose
        self._pose_buffer = deque(
            [POSE_NONE] * self._BUFFER_SIZE, maxlen=self._BUFFER_SIZE
        )
        self._active_pose = POSE_NONE

        # --- Alt-held state (OPEN_HAND gesture) ---
        self._alt_held = False
        # Timestamp of the last frame where active_pose == OPEN_HAND.
        # Used by the timeout safety check.
        self._last_open_hand_time = 0.0

        # ---- Per-pose tracking state ----
        # (all reset on every active-pose transition so stale data can't leak)

        # TWO_FINGER scroll
        self._scroll_first_frame = True
        self._scroll_prev_x      = 0.0
        self._scroll_prev_y      = 0.0
        self._scroll_axis        = None   # None=unlocked, 'v'=vertical, 'h'=horizontal
        self._scroll_accum_dx    = 0.0
        self._scroll_accum_dy    = 0.0

        # FOUR_FINGER tab switch
        self._tab_first     = True
        self._tab_prev_x    = 0.0
        self._tab_prev_t    = 0.0
        self._tab_last_fire = 0.0

        # OPEN_HAND Alt-Tab step
        self._app_first     = True
        self._app_prev_x    = 0.0
        self._app_prev_t    = 0.0
        self._app_last_fire = 0.0

        # PINCH
        self._pinch_last_fire = 0.0

        # FIST app switch
        self._fist_first     = True
        self._fist_prev_x    = 0.0
        self._fist_prev_t    = 0.0
        self._fist_last_fire = 0.0

        # Debug display strings
        self._last_action = ""

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update(self, raw_pose, landmarks, now):
        """
        Call once per frame.

        raw_pose  — result of classify_pose() for this frame (POSE_NONE if no hand)
        landmarks — mediapipe landmark object for the primary hand, or None
        now       — time.monotonic() timestamp
        """
        self._pose_buffer.append(raw_pose)

        # Check if we have consensus on a new active pose
        candidate = self._dominant_pose()
        if candidate != self._active_pose:
            self._on_pose_transition(candidate, now)

        # Safety: release Alt if the hand vanished or we've been away from
        # OPEN_HAND too long — independent of the transition logic above
        self._check_alt_safety(raw_pose, landmarks, now)

        # Track last-seen time for OPEN_HAND (used by timeout safety above)
        if self._active_pose == POSE_OPEN_HAND:
            self._last_open_hand_time = now

        # Execute the gesture for the current active pose
        self._execute(landmarks, now)

    def get_debug_lines(self):
        """Return list of strings to overlay on the camera feed."""
        lines = [f"Pose: {self._active_pose}"]

        if self._active_pose == POSE_TWO_FINGER:
            if self._scroll_axis == 'v':
                lines.append("Axis: VERTICAL")
            elif self._scroll_axis == 'h':
                lines.append("Axis: HORIZONTAL")
            else:
                lines.append("Axis: (locking...)")

        if self._alt_held:
            lines.append("Alt: HELD")

        if self._last_action:
            lines.append(self._last_action)

        return lines

    def force_cleanup(self):
        """Call on shutdown to ensure Alt is never left stuck down."""
        if self._alt_held:
            pyautogui.keyUp("alt")
            self._alt_held = False

    # ------------------------------------------------------------------
    # Internal — pose transition
    # ------------------------------------------------------------------

    def _dominant_pose(self):
        """
        Return the pose with >= _AGREE_NEEDED occurrences in the buffer.
        If no pose has consensus, keep the current active pose (hysteresis).
        """
        counts = {}
        for p in self._pose_buffer:
            counts[p] = counts.get(p, 0) + 1
        best_pose, best_count = max(counts.items(), key=lambda kv: kv[1])
        if best_count >= self._AGREE_NEEDED:
            return best_pose
        return self._active_pose

    def _on_pose_transition(self, new_pose, now):
        """
        Handle the exact moment the active pose changes.

        CRITICAL: Alt release lives here, NOT inside the OPEN_HAND branch,
        so it fires regardless of which pose we're transitioning to.
        """
        # Release Alt whenever we leave any pose (safe no-op if not held)
        if self._alt_held:
            pyautogui.keyUp("alt")
            self._alt_held = False
            self._last_action = "→ Alt released"

        # Reset ALL per-pose tracking — stale position/velocity data from
        # the previous pose must never bleed into the new one
        self._scroll_first_frame = True
        self._scroll_prev_x      = 0.0
        self._scroll_prev_y      = 0.0
        self._scroll_axis        = None
        self._scroll_accum_dx    = 0.0
        self._scroll_accum_dy    = 0.0

        self._tab_first  = True
        self._tab_prev_x = 0.0
        self._tab_prev_t = 0.0

        self._app_first  = True
        self._app_prev_x = 0.0
        self._app_prev_t = 0.0

        self._fist_first  = True
        self._fist_prev_x = 0.0
        self._fist_prev_t = 0.0

        self._active_pose = new_pose

    # ------------------------------------------------------------------
    # Internal — Alt safety
    # ------------------------------------------------------------------

    def _check_alt_safety(self, raw_pose, landmarks, now):
        """
        Two independent triggers that force-release Alt — whichever fires first:
          1. Hand completely disappeared (MediaPipe returned no landmarks).
          2. More than alt_release_timeout seconds have passed without OPEN_HAND.

        This runs every frame AFTER the transition check, making it a second
        independent safety net.
        """
        if not self._alt_held:
            return

        hand_gone = (landmarks is None)
        timeout   = (now - self._last_open_hand_time) > self._cfg["alt_release_timeout"]

        if hand_gone or timeout:
            pyautogui.keyUp("alt")
            self._alt_held = False
            reason = "hand lost" if hand_gone else "timeout"
            self._last_action = f"→ Alt force-released ({reason})"

    # ------------------------------------------------------------------
    # Internal — gesture dispatch
    # ------------------------------------------------------------------

    def _execute(self, landmarks, now):
        pose = self._active_pose

        if pose in (POSE_NONE, POSE_FIST):
            # NONE: nothing to do.
            # FIST: pause — do nothing.
            pass

        elif pose == POSE_PINCH:
            self._do_pinch(now)

        elif pose == POSE_TWO_FINGER:
            if landmarks is not None:
                self._do_two_finger_scroll(landmarks, now)

        elif pose == POSE_FOUR_FINGER:
            if landmarks is not None:
                self._do_four_finger_tab(landmarks, now)

        elif pose == POSE_OPEN_HAND:
            if landmarks is not None:
                self._do_open_hand_app_switch(landmarks, now)

    # ------------------------------------------------------------------
    # Internal — individual gesture implementations
    # ------------------------------------------------------------------

    def _do_pinch(self, now):
        """
        Press pinch_key once per like_key_cooldown seconds.
        Holding the pinch does NOT spam the key.
        """
        if (now - self._pinch_last_fire) >= self._cfg["like_key_cooldown"]:
            key = self._cfg["pinch_key"]
            pyautogui.press(key)
            self._pinch_last_fire = now
            self._last_action = f"→ '{key}' pressed (pinch)"

    def _do_two_finger_scroll(self, landmarks, now):
        """
        Delta-based trackpad-style scroll.

        Axis is locked after the first axis's accumulated displacement exceeds
        axis_lock_threshold, preventing a slightly diagonal swipe from
        flickering between vertical and horizontal scrolling.

        Sign convention (verified):
          dy < 0  → fingers moved UP the frame  → scroll(negative) = scroll DOWN ✓
          dy > 0  → fingers moved DOWN the frame → scroll(positive) = scroll UP  ✓
        """
        cfg = self._cfg
        idx = landmarks.landmark[HL.INDEX_FINGER_TIP]
        mid = landmarks.landmark[HL.MIDDLE_FINGER_TIP]
        cur_x = (idx.x + mid.x) / 2.0
        cur_y = (idx.y + mid.y) / 2.0

        if self._scroll_first_frame:
            self._scroll_prev_x      = cur_x
            self._scroll_prev_y      = cur_y
            self._scroll_first_frame = False
            return

        dx = cur_x - self._scroll_prev_x
        dy = cur_y - self._scroll_prev_y
        self._scroll_prev_x = cur_x
        self._scroll_prev_y = cur_y

        # Accumulate absolute displacement to decide axis lock
        if self._scroll_axis is None:
            self._scroll_accum_dx += abs(dx)
            self._scroll_accum_dy += abs(dy)
            t = cfg["axis_lock_threshold"]
            # Lock to whichever axis surpasses the threshold first
            if self._scroll_accum_dx >= t or self._scroll_accum_dy >= t:
                self._scroll_axis = (
                    'h' if self._scroll_accum_dx > self._scroll_accum_dy else 'v'
                )

        if self._scroll_axis == 'v':
            # scroll_sensitivity: raise = faster scroll per cm of hand travel
            amount = int(dy * cfg["scroll_sensitivity"])
            if amount != 0:
                pyautogui.scroll(amount)
                self._last_action = ("↑ scroll up" if amount > 0 else "↓ scroll down")

        elif self._scroll_axis == 'h':
            amount = int(dx * cfg["scroll_sensitivity"])
            if amount != 0:
                pyautogui.hscroll(amount)
                self._last_action = ("→ scroll right" if amount > 0 else "← scroll left")

    def _do_four_finger_tab(self, landmarks, now):
        """
        One-shot Chrome tab switch on a fast horizontal swipe.
        tab_swipe_velocity: lower = triggers on slower swipes.
        tab_swipe_cooldown: lower = allows faster repeated switching.
        """
        cfg = self._cfg
        tips = [
            landmarks.landmark[HL.INDEX_FINGER_TIP],
            landmarks.landmark[HL.MIDDLE_FINGER_TIP],
            landmarks.landmark[HL.RING_FINGER_TIP],
            landmarks.landmark[HL.PINKY_TIP],
        ]
        cur_x = sum(t.x for t in tips) / 4.0

        if self._tab_first:
            self._tab_prev_x = cur_x
            self._tab_prev_t = now
            self._tab_first  = False
            return

        dt = now - self._tab_prev_t
        if dt < 1e-6:
            return

        velocity = (cur_x - self._tab_prev_x) / dt   # normalized widths / sec
        self._tab_prev_x = cur_x
        self._tab_prev_t = now

        if (now - self._tab_last_fire) < cfg["tab_swipe_cooldown"]:
            return  # Still in cooldown; ignore this frame

        if velocity > cfg["tab_swipe_velocity"]:
            pyautogui.hotkey("ctrl", "tab")
            self._tab_last_fire = now
            self._last_action = "→ next tab (Ctrl+Tab)"

        elif velocity < -cfg["tab_swipe_velocity"]:
            pyautogui.hotkey("ctrl", "shift", "tab")
            self._tab_last_fire = now
            self._last_action = "← prev tab (Ctrl+Shift+Tab)"

    def _do_open_hand_app_switch(self, landmarks, now):
        """
        One-shot app switch on a fast horizontal open-hand swipe.

        Open hand swipes RIGHT → Alt+Tab           (next app)
        Open hand swipes LEFT  → Alt+Shift+Tab     (previous app)

        Each swipe is a quick press-and-release — Windows commits the switch
        immediately, no Alt is held between swipes.

        Tracks the WRIST for a stable reference point (fingertip spread on an
        open hand can wobble; wrist stays steady during a horizontal swipe).

        app_swipe_velocity: lower = triggers on slower swipes
        app_swipe_cooldown: raise if one swipe switches more than one app
        """
        cfg  = self._cfg
        wrist = landmarks.landmark[HL.WRIST]
        cur_x = wrist.x

        if self._app_first:
            self._app_prev_x = cur_x
            self._app_prev_t = now
            self._app_first  = False
            return

        dt = now - self._app_prev_t
        if dt < 1e-6:
            return

        velocity = (cur_x - self._app_prev_x) / dt   # normalized widths / sec
        self._app_prev_x = cur_x
        self._app_prev_t = now

        if (now - self._app_last_fire) < cfg["app_swipe_cooldown"]:
            return  # Cooldown — ignore this frame

        if velocity > cfg["app_swipe_velocity"]:
            pyautogui.hotkey("alt", "tab")
            self._app_last_fire = now
            self._last_action = "→ next app (open hand right)"

        elif velocity < -cfg["app_swipe_velocity"]:
            pyautogui.hotkey("alt", "shift", "tab")
            self._app_last_fire = now
            self._last_action = "← prev app (open hand left)"


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def main():
    config = load_config()

    # Rotation (do not touch — kept exactly as baseline)
    rotation    = config["rotation"]
    rotate_code = _ROTATION_MAP.get(rotation)
    if rotation not in _ROTATION_MAP:
        print(f"WARNING: Unknown rotation '{rotation}', using none.")
        rotate_code = None

    overlay_w, overlay_h = overlay_size(rotation)

    cap = cv2.VideoCapture(config["camera_index"])
    cap.set(cv2.CAP_PROP_FRAME_WIDTH,  640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

    if not cap.isOpened():
        print("ERROR: Could not open camera. Make sure no other app is using it.")
        return

    overlay    = SkeletonOverlay(overlay_w, overlay_h)
    controller = GestureController(config)

    camera_hidden = False
    fullscreen    = False
    first_frame   = True
    CAMERA_WIN    = "Hand Skeleton"
    # WINDOW_KEEPRATIO keeps portrait feed un-stretched when maximised/fullscreen
    cv2.namedWindow(CAMERA_WIN, cv2.WINDOW_NORMAL | cv2.WINDOW_KEEPRATIO)

    with mp_hands.Hands(
        model_complexity=0,
        min_detection_confidence=0.75,
        min_tracking_confidence=0.65,
        max_num_hands=2,
    ) as hands:
        while cap.isOpened():
            ret, frame = cap.read()
            if not ret:
                break

            # Optional rotation then mirror for selfie view (unchanged from baseline)
            if rotate_code is not None:
                frame = cv2.rotate(frame, rotate_code)
            frame = cv2.flip(frame, 1)
            h, w = frame.shape[:2]

            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            rgb.flags.writeable = False
            results = hands.process(rgb)
            rgb.flags.writeable = True

            detected = results.multi_hand_landmarks or []

            overlay_hands = []
            for hand in detected:
                draw_glowing_hand(frame, hand, w, h, HAND_BGR)
                overlay_hands.append((hand, HAND_HEX))

            overlay.set_hands(overlay_hands)
            overlay.refresh()

            # Use the first detected hand for gesture classification.
            # (With max_num_hands=2 the primary hand is always index 0.)
            now = time.monotonic()
            if detected:
                primary      = detected[0]
                raw_pose     = classify_pose(primary, config)
                primary_lm   = primary
            else:
                primary_lm   = None
                raw_pose     = POSE_NONE

            controller.update(raw_pose, primary_lm, now)

            if not camera_hidden:
                draw_hint(frame, w, h)
                draw_debug(frame, controller.get_debug_lines(), h)
                cv2.imshow(CAMERA_WIN, frame)
                if first_frame:
                    cv2.resizeWindow(CAMERA_WIN, w, h)
                    first_frame = False
            else:
                cv2.imshow(CAMERA_WIN, np.zeros((1, 1, 3), dtype=np.uint8))

            key = cv2.waitKey(1) & 0xFF
            if key == ord("q") or overlay.quit_requested():
                break
            elif key == ord("f"):
                fullscreen = not fullscreen
                cv2.setWindowProperty(
                    CAMERA_WIN, cv2.WND_PROP_FULLSCREEN,
                    cv2.WINDOW_FULLSCREEN if fullscreen else cv2.WINDOW_NORMAL)
            elif key == ord("h"):
                camera_hidden = not camera_hidden
            elif key == ord("o"):
                overlay.toggle()

    # Cleanup — always release Alt if it's somehow still held on exit
    controller.force_cleanup()
    cap.release()
    cv2.destroyAllWindows()
    overlay.destroy()


if __name__ == "__main__":
    main()
