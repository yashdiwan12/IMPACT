from flask import Flask, request, jsonify
from flask_cors import CORS
import joblib
import os
import io
import base64
from PIL import Image
from ultralytics import YOLO

app = Flask(__name__)
CORS(app)

# Load machine learning models dynamically from the parent directory
MODEL_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "ML Model")
vectorizer = joblib.load(os.path.join(MODEL_DIR, 'tfidf_vectorizer.pkl'))
cat_model = joblib.load(os.path.join(MODEL_DIR, 'category_model.pkl'))
sev_model = joblib.load(os.path.join(MODEL_DIR, 'severity_model.pkl'))
yolo_model = YOLO(os.path.join(MODEL_DIR, 'best (1).pt'))

@app.route("/api/ml/analyze-text", methods=["POST"])
def analyze_text():
    data = request.json
    text = data.get("text", "")
    if not text.strip():
        return jsonify({"category": "", "severity": ""})
    
    vec = vectorizer.transform([text])
    cat = cat_model.predict(vec)[0]
    sev = sev_model.predict(vec)[0]
    return jsonify({"category": cat, "severity": sev})

@app.route("/api/ml/analyze-image", methods=["POST"])
def analyze_image():
    try:
        data = request.json
        img_str = data.get("image", "")
        if not img_str:
            return jsonify({"detections": [], "summary": ""})
            
        if "base64," in img_str:
            img_str = img_str.split("base64,")[1]
            
        img_data = base64.b64decode(img_str)
        img = Image.open(io.BytesIO(img_data))
        
        # Generate bounding boxes and confidence scores
        results = yolo_model(img)
        
        detections = []
        for r in results:
            for box in r.boxes:
                cls_id = int(box.cls[0].item())
                conf = float(box.conf[0].item())
                cls_name = yolo_model.names[cls_id]
                detections.append({"class": cls_name, "confidence": round(conf, 2)})
                
        unique_classes = list(set([d['class'] for d in detections]))
        return jsonify({"detections": detections, "summary": ", ".join(unique_classes)})
    except Exception as e:
        return jsonify({"error": str(e), "detections": [], "summary": ""}), 400

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port)
