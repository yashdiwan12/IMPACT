from flask import Flask, request, jsonify
from flask_cors import CORS
import os
import io
import base64
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

# ---------------------------------------------------------------------------
# Lazy-loaded models — loaded on first request, NOT at import time.
# This lets gunicorn bind the port immediately so Render doesn't time out.
# ---------------------------------------------------------------------------
_models = {}

MODEL_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "ML Model")


def _get_text_models():
    """Lazy-load the TF-IDF vectorizer + category/severity classifiers."""
    if "vectorizer" not in _models:
        import joblib
        logger.info("Loading text models from %s …", MODEL_DIR)
        _models["vectorizer"] = joblib.load(os.path.join(MODEL_DIR, "tfidf_vectorizer.pkl"))
        _models["cat_model"] = joblib.load(os.path.join(MODEL_DIR, "category_model.pkl"))
        _models["sev_model"] = joblib.load(os.path.join(MODEL_DIR, "severity_model.pkl"))
        logger.info("Text models loaded ✓")
    return _models["vectorizer"], _models["cat_model"], _models["sev_model"]


def _get_yolo_model():
    """Lazy-load the YOLO model (heavy — pulls in ultralytics + torch)."""
    if "yolo" not in _models:
        from ultralytics import YOLO
        logger.info("Loading YOLO model from %s …", MODEL_DIR)
        _models["yolo"] = YOLO(os.path.join(MODEL_DIR, "best (1).pt"))
        logger.info("YOLO model loaded ✓")
    return _models["yolo"]


# ---------------------------------------------------------------------------
# Health-check — responds instantly so Render confirms port binding
# ---------------------------------------------------------------------------
@app.route("/health")
def health():
    return jsonify({"status": "ok"}), 200


@app.route("/api/ml/analyze-text", methods=["POST"])
def analyze_text():
    data = request.json
    text = data.get("text", "")
    if not text.strip():
        return jsonify({"category": "", "severity": ""})

    vectorizer, cat_model, sev_model = _get_text_models()

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

        from PIL import Image
        img_data = base64.b64decode(img_str)
        img = Image.open(io.BytesIO(img_data))

        yolo_model = _get_yolo_model()

        # Generate bounding boxes and confidence scores
        results = yolo_model(img)

        detections = []
        for r in results:
            for box in r.boxes:
                cls_id = int(box.cls[0].item())
                conf = float(box.conf[0].item())
                cls_name = yolo_model.names[cls_id]
                detections.append({"class": cls_name, "confidence": round(conf, 2)})

        unique_classes = list(set([d["class"] for d in detections]))
        return jsonify({"detections": detections, "summary": ", ".join(unique_classes)})
    except Exception as e:
        logger.exception("Image analysis failed")
        return jsonify({"error": str(e), "detections": [], "summary": ""}), 400


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port)
