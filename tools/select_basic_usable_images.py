import argparse
import csv
import json
import shutil
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import mediapipe_ascii  # noqa: F401,E402  # 必須早於 mediapipe，見該模組說明
import mediapipe as mp  # noqa: E402


def landmark_xy(landmarks, index, width, height):
    lm = landmarks[index]
    return np.array([lm.x * width, lm.y * height], dtype=np.float32)


def assess_basic_usable(image_path, face_mesh):
    image = cv2.imread(str(image_path))
    if image is None:
        return False, "read_failed"

    height, width = image.shape[:2]
    if width < 128 or height < 128:
        return False, "too_small"

    rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    result = face_mesh.process(rgb)
    faces = result.multi_face_landmarks or []
    if len(faces) != 1:
        return False, "face_count_not_one"

    landmarks = faces[0].landmark
    left_eye = landmark_xy(landmarks, 33, width, height)
    right_eye = landmark_xy(landmarks, 263, width, height)
    nose = landmark_xy(landmarks, 1, width, height)
    chin = landmark_xy(landmarks, 152, width, height)
    forehead = landmark_xy(landmarks, 10, width, height)
    left_cheek = landmark_xy(landmarks, 234, width, height)
    right_cheek = landmark_xy(landmarks, 454, width, height)

    face_width = float(np.linalg.norm(right_cheek - left_cheek))
    face_height = float(np.linalg.norm(chin - forehead))
    if face_width < width * 0.28 or face_height < height * 0.38:
        return False, "face_too_small"

    eye_dx = abs(float(right_eye[0] - left_eye[0]))
    eye_dy = abs(float(right_eye[1] - left_eye[1]))
    if eye_dx <= 1 or eye_dy / eye_dx > 0.12:
        return False, "tilted_face"

    eye_center_x = float((left_eye[0] + right_eye[0]) / 2)
    nose_offset = abs(float(nose[0] - eye_center_x)) / max(eye_dx, 1.0)
    if nose_offset > 0.18:
        return False, "not_frontal"

    center_x = float((left_cheek[0] + right_cheek[0]) / 2)
    if abs(center_x - width / 2) / width > 0.20:
        return False, "face_off_center"

    if not (0 <= forehead[1] < chin[1] <= height):
        return False, "bad_landmark_geometry"

    return True, "basic_usable"


def main():
    parser = argparse.ArgumentParser(description="Select CelebA images usable for BASIC frontal face labeling.")
    parser.add_argument("--source", default="celeba_raw/img_align_celeba/img_align_celeba")
    parser.add_argument("--output", default="data/basic_usable/raw_images")
    parser.add_argument("--target", type=int, default=500)
    parser.add_argument("--max-scan", type=int, default=10000)
    args = parser.parse_args()

    source = Path(args.source)
    output = Path(args.output)
    manifest = output.parent / "selection_manifest.csv"
    labels_csv = output.parent / "labels.csv"
    split_csv = output.parent / "split.csv"
    label_map_json = output.parent / "label_map.json"
    stats_json = output.parent / "dataset_stats.json"
    rejected_csv = output.parent / "rejected.csv"

    output.mkdir(parents=True, exist_ok=True)

    selected = []
    rejected = []
    candidates = sorted(source.glob("*.jpg"))
    if not candidates:
        raise SystemExit(f"No jpg images found in {source}")

    face_mesh = mp.solutions.face_mesh.FaceMesh(
        static_image_mode=True,
        max_num_faces=1,
        refine_landmarks=False,
        min_detection_confidence=0.5,
    )

    try:
        for index, image_path in enumerate(candidates[: args.max_scan], start=1):
            ok, reason = assess_basic_usable(image_path, face_mesh)
            if ok:
                destination = output / image_path.name
                if not destination.exists():
                    shutil.copy2(image_path, destination)
                selected.append((image_path.name, str(destination), reason))
                if len(selected) >= args.target:
                    break
            else:
                rejected.append((image_path.name, reason))

            if index % 200 == 0:
                print(f"scanned={index} selected={len(selected)} rejected={len(rejected)}")
    finally:
        face_mesh.close()

    with manifest.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["image_id", "file_path", "reason"])
        writer.writerows(selected)

    with labels_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["image_id", "file_path", "face_shape", "nose_front", "eye_shape", "brow_shape", "lip_shape", "quality", "note"])
        for image_id, file_path, _ in selected:
            writer.writerow([image_id, file_path, "", "", "", "", "", "good", "basic_usable_prefilter"])

    with split_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["image_id", "split"])
        for idx, (image_id, _, _) in enumerate(selected):
            split = "val" if idx % 5 == 0 else "train"
            writer.writerow([image_id, split])

    label_map = {
        "face_shape": ["心形臉", "方形臉", "長形臉", "圓形臉", "鵝蛋臉"],
        "nose_front": ["窄鼻", "寬鼻", "標準鼻"],
        "eye_shape": ["下垂眼", "丹鳳眼", "杏仁眼", "桃花眼", "細長眼", "圓眼", "瞇縫眼"],
        "brow_shape": ["一字眉", "落尾眉", "彎月眉"],
        "lip_shape": ["花瓣唇", "厚唇", "微笑唇", "薄唇"],
        "quality": ["good", "ok", "bad"],
    }
    label_map_json.write_text(json.dumps(label_map, ensure_ascii=False, indent=2), encoding="utf-8")

    with rejected_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["image_id", "reason"])
        writer.writerows(rejected)

    stats = {
        "source": str(source),
        "output": str(output),
        "target": args.target,
        "max_scan": args.max_scan,
        "selected": len(selected),
        "rejected": len(rejected),
        "train": sum(1 for idx, _ in enumerate(selected) if idx % 5 != 0),
        "val": sum(1 for idx, _ in enumerate(selected) if idx % 5 == 0),
    }
    stats_json.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"done selected={len(selected)} rejected={len(rejected)}")
    print(f"output={output}")
    print(f"labels={labels_csv}")
    print(f"split={split_csv}")
    print(f"label_map={label_map_json}")


if __name__ == "__main__":
    main()
