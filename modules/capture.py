import cv2
import os

def capture_face(user_id, user_name):
    cam = cv2.VideoCapture(0)
    face_detector = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')

    print(f"\n [INFO] Initializing face capture for {user_name}. Look at the camera...")
    count = 0

    while(True):
        ret, frame = cam.read()
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = face_detector.detectMultiScale(gray, 1.3, 5)

        for (x,y,w,h) in faces:
            cv2.rectangle(frame, (x,y), (x+w,y+h), (255,0,0), 2)     
            count += 1

            # Ise-save ang picture sa faces folder
            # Format: ID.Name.SampleNumber.jpg
            file_name = f"faces/{user_id}.{user_name}.{count}.jpg"
            cv2.imwrite(file_name, gray[y:y+h,x:x+w])

            cv2.imshow('Registering Face - Press ESC to cancel', frame)

        k = cv2.waitKey(100) & 0xff
        if k == 27: # ESC key para tumigil
            break
        elif count >= 30: # Kukuha ng 30 samples tapos titigil na
             break

    print(f"\n [SUCCESS] Captured {count} images for {user_name}")
    cam.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    # Test run lang ito
    uid = input("Enter User ID: ")
    uname = input("Enter Name: ")
    capture_face(uid, uname)