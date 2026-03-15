import cv2
import mediapipe as mp
from mediapipe.python.solutions.face_mesh_connections import FACEMESH_FACE_OVAL

mp_face_mesh = mp.solutions.face_mesh
face_mesh = mp_face_mesh.FaceMesh(
    max_num_faces=1,
    refine_landmarks=True,
    min_detection_confidence=0.5,
    min_tracking_confidence=0.5,
)

COLOR = (0, 212, 255)  # 青色

def draw_oval(frame, lm, show_index=False):
    h, w = frame.shape[:2]

    # 畫連線
    for (a, b) in FACEMESH_FACE_OVAL:
        x1, y1 = int(lm[a].x * w), int(lm[a].y * h)
        x2, y2 = int(lm[b].x * w), int(lm[b].y * h)
        cv2.line(frame, (x1, y1), (x2, y2), COLOR, 1)

    # 畫點位
    indices = set()
    for (a, b) in FACEMESH_FACE_OVAL:
        indices.add(a)
        indices.add(b)

    for i in indices:
        x, y = int(lm[i].x * w), int(lm[i].y * h)
        cv2.circle(frame, (x, y), 3, COLOR, -1)
        if show_index:
            cv2.putText(frame, str(i), (x + 4, y - 4),
                        cv2.FONT_HERSHEY_PLAIN, 0.8, COLOR, 1)

def main():
    cap = cv2.VideoCapture(0)
    show_index = False

    print("'i' → 切換點位編號  |  'q' → 離開")

    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            break

        frame = cv2.flip(frame, 1)
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = face_mesh.process(rgb)

        if results.multi_face_landmarks:
            lm = results.multi_face_landmarks[0].landmark
            draw_oval(frame, lm, show_index)

        hint = "INDEX: ON [i]" if show_index else "INDEX: OFF [i]"
        cv2.putText(frame, hint, (10, frame.shape[0] - 10),
                    cv2.FONT_HERSHEY_PLAIN, 1.0, (150, 150, 150), 1)

        cv2.imshow("Face Oval", frame)

        key = cv2.waitKey(1) & 0xFF
        if key == ord('q'):
            break
        elif key == ord('i'):
            show_index = not show_index

    cap.release()
    cv2.destroyAllWindows()
    face_mesh.close()

if __name__ == "__main__":
    main()