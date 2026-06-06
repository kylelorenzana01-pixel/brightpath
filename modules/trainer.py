import cv2
import os
import numpy as np
import json
import glob

def train_faces():
    """
    Trains the face recognizer using images from static/faces folder.
    Expects filename format: {user_id}.{user_name}.{count}.jpg
    Uses CLAHE for lighting-invariant preprocessing.
    The images are already cropped faces (200x200), so no face detection is needed.
    """
    faces_path = 'static/faces'
    trainer_path = 'static/trainer.yml'
    user_map_path = 'static/user_map.json'
    
    if not os.path.exists(faces_path):
        print("❌ Error: 'static/faces' folder does not exist!")
        return False
    
    image_pattern = os.path.join(faces_path, "*.jpg")
    image_files = glob.glob(image_pattern)
    
    if len(image_files) == 0:
        print("❌ Error: No face images found in static/faces!")
        print("   Expected format: {user_id}.{user_name}.{count}.jpg")
        return False
    
    print(f"📸 Found {len(image_files)} face images. Starting training...")
    
    recognizer = cv2.face.LBPHFaceRecognizer_create()
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8))
    
    face_samples = []
    ids = []
    user_map = {}
    
    for img_path in image_files:
        filename = os.path.basename(img_path)
        parts = filename.split('.')
        
        if len(parts) >= 3:
            try:
                user_id = int(parts[0])
                user_name = parts[1]
                
                if user_id not in user_map:
                    user_map[user_id] = user_name
                
                img = cv2.imread(img_path, cv2.IMREAD_GRAYSCALE)
                if img is None:
                    print(f"⚠️ Warning: Could not read {filename}")
                    continue
                
                # Apply CLAHE for better lighting invariance
                img = clahe.apply(img)
                
                # Images are already cropped faces (200x200 from capture_frame)
                # Just resize to a consistent size (already 200x200, but safe)
                face_resized = cv2.resize(img, (200, 200))
                face_samples.append(face_resized)
                ids.append(user_id)
                
                print(f"   ✓ Processed: {filename} (ID: {user_id})")
                
            except ValueError as e:
                print(f"⚠️ Warning: Invalid filename format: {filename}")
                continue
            except Exception as e:
                print(f"⚠️ Warning: Error processing {filename}: {e}")
                continue
    
    if len(face_samples) == 0:
        print("❌ Error: No valid face samples found for training!")
        return False
    
    print(f"\n🔄 Training with {len(face_samples)} samples from {len(user_map)} users...")
    recognizer.train(face_samples, np.array(ids))
    
    recognizer.write(trainer_path)
    print(f"✅ Saved trainer to: {trainer_path}")
    
    user_map_str_keys = {str(k): v for k, v in user_map.items()}
    with open(user_map_path, 'w') as f:
        json.dump(user_map_str_keys, f, indent=2)
    
    print(f"✅ Saved user map to: {user_map_path}")
    print(f"\n📊 Training Summary:")
    print(f"   - Total Users: {len(user_map)}")
    print(f"   - Total Samples: {len(face_samples)}")
    print(f"   - Users: {list(user_map.values())}")
    
    return True

def check_training_status():
    """Check if training files exist and are valid"""
    trainer_exists = os.path.exists('static/trainer.yml')
    usermap_exists = os.path.exists('static/user_map.json')
    
    if trainer_exists and usermap_exists:
        print("✅ Training files exist and are ready")
        with open('static/user_map.json', 'r') as f:
            user_map = json.load(f)
        print(f"   Registered users: {len(user_map)}")
        for uid, name in user_map.items():
            print(f"     - ID {uid}: {name}")
        return True
    else:
        print("❌ Training files missing or incomplete")
        return False

if __name__ == "__main__":
    print("=" * 50)
    print("FACE RECOGNITION TRAINER")
    print("=" * 50)
    train_faces()
    print("\n" + "=" * 50)
    check_training_status()