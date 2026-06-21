import json
from pathlib import Path

import cv2
import mediapipe as mp
import numpy as np
import tkinter as tk

mp_hands = mp.solutions.hands

HAND_CONNECTIONS = list(mp_hands.HAND_CONNECTIONS)

_ROTATION_MAP = {
    "none": None,
    "cw": cv2.ROTATE_90_CLOCKWISE,           # 90° right
    "ccw": cv2.ROTATE_90_COUNTERCLOCKWISE,   # 90° left
    "180": cv2.ROTATE_180,
}


def load_config():
    config_path = Path(__file__).with_name("config.json")
    defaults = {"camera_index": 0, "rotation": "none"}
    if not config_path.exists():
        return defaults
    with config_path.open(encoding="utf-8") as f:
        data = json.load(f)
    return {**defaults, **data}


def overlay_size(rotation):
    # Portrait when rotated 90°; landscape when not.
    if rotation in ("cw", "ccw"):
        return 180, 240
    return 240, 180

# Transparent color key — pixels this color become see-through
_TRANSPARENT_KEY = "black"

HAND_HEX = "#00FF88"   # green skeleton
HAND_BGR = (136, 255, 0)


# ---------------------------------------------------------------------------
# Floating overlay window
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
# Skeleton drawing on the main camera window
# ---------------------------------------------------------------------------

def draw_glowing_hand(frame, hand_landmarks, w, h, color=HAND_BGR):
    glow = frame.copy()
    for connection in HAND_CONNECTIONS:
        start = hand_landmarks.landmark[connection[0]]
        end = hand_landmarks.landmark[connection[1]]
        x1, y1 = int(start.x * w), int(start.y * h)
        x2, y2 = int(end.x * w), int(end.y * h)
        cv2.line(glow, (x1, y1), (x2, y2), color, 12)
    cv2.addWeighted(glow, 0.35, frame, 0.65, 0, frame)

    for connection in HAND_CONNECTIONS:
        start = hand_landmarks.landmark[connection[0]]
        end = hand_landmarks.landmark[connection[1]]
        x1, y1 = int(start.x * w), int(start.y * h)
        x2, y2 = int(end.x * w), int(end.y * h)
        cv2.line(frame, (x1, y1), (x2, y2), color, 2)

    for lm in hand_landmarks.landmark:
        cx, cy = int(lm.x * w), int(lm.y * h)
        cv2.circle(frame, (cx, cy), 6, (255, 255, 255), -1)
        cv2.circle(frame, (cx, cy), 8, color, 1)


def draw_hint(frame, w, h):
    cv2.putText(frame, "Q=quit  F=fullscreen  H=hide cam  O=overlay",
                (10, h - 12), cv2.FONT_HERSHEY_SIMPLEX, 0.4,
                (90, 90, 90), 1, cv2.LINE_AA)


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def main():
    config = load_config()
    rotation = config["rotation"]
    rotate_code = _ROTATION_MAP.get(rotation)
    if rotation not in _ROTATION_MAP:
        print(f"WARNING: Unknown rotation '{rotation}', using none.")
        rotate_code = None

    overlay_w, overlay_h = overlay_size(rotation)

    cap = cv2.VideoCapture(config["camera_index"])
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

    if not cap.isOpened():
        print("ERROR: Could not open camera. Make sure no other app is using it.")
        return

    overlay = SkeletonOverlay(overlay_w, overlay_h)

    camera_hidden = False
    fullscreen = False
    first_frame = True
    CAMERA_WIN = "Hand Skeleton"
    # KEEPRATIO keeps the portrait feed un-stretched (letterboxed) when the
    # window is maximized or made fullscreen.
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

            # Optional rotation (see config.json), then mirror for selfie view.
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

            if not camera_hidden:
                draw_hint(frame, w, h)
                cv2.imshow(CAMERA_WIN, frame)
                # Size the window to the frame only once, on the first frame.
                # After that the user is free to maximize / resize / fullscreen
                # without the loop snapping it back.
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

    cap.release()
    cv2.destroyAllWindows()
    overlay.destroy()


if __name__ == "__main__":
    main()
