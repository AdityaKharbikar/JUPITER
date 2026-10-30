# 3D viewer controls

Say "what are the 3D voice commands" any time to hear/see this list.

3D VIEWER - VOICE COMMANDS (say them after a model is open)
Rotate: "rotate left / right / up / down", "auto rotate", "top view"
Zoom: "zoom in", "zoom out", "closer", "further away"      Move: "pan left / right / up / down"
Explode: "explode", "assemble" (or "put it together")       Tour: "start assembly", "stop"
Display: "x-ray", "show labels", "hide labels", "isolate"   View: "reset view"
Parts: "select <part name>" (e.g. "select piston"), "next part", "previous part", "deselect"
Hands: "enable hand control" / "disable hand control"

HAND GESTURES (webcam, hand control ON; mirror view)
Open palm + move = rotate | Fist + move = pan | Two hands apart / together = zoom in / out
Index finger = pointer (hover) | Pinch thumb+index = click / select part
Peace sign (hold 1s) = explode / assemble | Thumbs up (hold) = x-ray | Call-me sign (thumb+pinky, hold) = labels
Three fingers (hold) = play assembly | Open palm held still 1.5s = stop

Hand control: click "Hand control" in the viewer window or say "enable hand control". Needs `pip install opencv-python mediapipe`. Frames are processed in memory only.
