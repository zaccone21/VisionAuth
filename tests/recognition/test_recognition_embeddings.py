"""Unit tests for the recognition embeddings module."""

import numpy as np
import os
import json
import pytest
from unittest.mock import patch, MagicMock
from visionauth.recognition.recognition_embeddings import (
    EMBEDDING_DIMENSION,
    EMBEDDING_MODEL,
    EMBEDDING_VERSION,
    MODELS_DIR,
    RECOGNIZER_MODEL_FILE,
    EmbeddingExtractor,
    EmbeddingMatcher,
    cosine_similarity,
    is_profile_compatible,
)


def test_cosine_similarity() -> None:
    # Identical L2 normalized vectors
    emb1 = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    emb2 = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    assert abs(cosine_similarity(emb1, emb2) - 1.0) < 1e-6

    # Orthogonal vectors
    emb3 = np.array([0.0, 1.0, 0.0], dtype=np.float32)
    assert abs(cosine_similarity(emb1, emb3) - 0.0) < 1e-6

    # Opposite vectors
    emb4 = np.array([-1.0, 0.0, 0.0], dtype=np.float32)
    assert abs(cosine_similarity(emb1, emb4) - (-1.0)) < 1e-6


def test_missing_model() -> None:
    with pytest.raises(FileNotFoundError):
        EmbeddingExtractor(model_path="nonexistent_model_file.onnx")


def test_invalid_model(tmp_path) -> None:
    model_file = tmp_path / "invalid_model.onnx"
    model_file.write_text("not a real onnx model")
    with pytest.raises(RuntimeError):
        EmbeddingExtractor(model_path=str(model_file))


@patch("cv2.FaceRecognizerSF.create")
def test_incorrect_dimension(mock_create, tmp_path) -> None:
    model_file = tmp_path / "dummy.onnx"
    model_file.write_text("dummy content")
    
    mock_recognizer = MagicMock()
    # Returns an output with the wrong dimension
    mock_recognizer.feature.return_value = np.ones((1, EMBEDDING_DIMENSION * 2), dtype=np.float32)
    mock_create.return_value = mock_recognizer
    
    with pytest.raises(RuntimeError) as excinfo:
        EmbeddingExtractor(model_path=str(model_file))
    assert "validation failed" in str(excinfo.value)


@patch("cv2.FaceRecognizerSF.create")
def test_nan_inf_embeddings(mock_create, tmp_path) -> None:
    model_file = tmp_path / "dummy.onnx"
    model_file.write_text("dummy content")
    
    # 1. Test NaN
    mock_recognizer = MagicMock()
    nan_arr = np.ones((1, EMBEDDING_DIMENSION), dtype=np.float32)
    nan_arr[0, 0] = np.nan
    mock_recognizer.feature.return_value = nan_arr
    mock_create.return_value = mock_recognizer
    
    with pytest.raises(RuntimeError) as excinfo:
        EmbeddingExtractor(model_path=str(model_file))
    assert "validation failed" in str(excinfo.value)
    
    # 2. Test Inf
    inf_arr = np.ones((1, EMBEDDING_DIMENSION), dtype=np.float32)
    inf_arr[0, 0] = np.inf
    mock_recognizer.feature.return_value = inf_arr
    
    with pytest.raises(RuntimeError) as excinfo:
        EmbeddingExtractor(model_path=str(model_file))
    assert "validation failed" in str(excinfo.value)


def test_incompatible_profile(tmp_path) -> None:
    data_dir = str(tmp_path)
    user_dir = os.path.join(data_dir, "users", "test_user")
    os.makedirs(user_dir, exist_ok=True)
    
    # Write a profile with wrong dimension
    profile = {
        "user": "test_user",
        "embeddings": [np.zeros(EMBEDDING_DIMENSION * 2).tolist()],
        "embedding_model": EMBEDDING_MODEL,
        "embedding_dimension": EMBEDDING_DIMENSION * 2,  # Incompatible
        "embedding_version": EMBEDDING_VERSION,
    }
    with open(os.path.join(user_dir, "profile.json"), "w") as f:
        json.dump(profile, f)
        
    matcher = EmbeddingMatcher(data_dir=data_dir)
    profiles = matcher.load_profiles()
    assert "test_user" not in profiles


def test_version_incompatible(tmp_path) -> None:
    data_dir = str(tmp_path)
    user_dir = os.path.join(data_dir, "users", "test_user")
    os.makedirs(user_dir, exist_ok=True)
    
    # Write profile with an older version
    profile = {
        "user": "test_user",
        "embeddings": [np.zeros(EMBEDDING_DIMENSION).tolist()],
        "embedding_model": EMBEDDING_MODEL,
        "embedding_dimension": EMBEDDING_DIMENSION,
        "embedding_version": EMBEDDING_VERSION - 1,  # Incompatible version
    }
    with open(os.path.join(user_dir, "profile.json"), "w") as f:
        json.dump(profile, f)
        
    matcher = EmbeddingMatcher(data_dir=data_dir)
    profiles = matcher.load_profiles()
    assert "test_user" not in profiles


def test_compatible_profile_match(tmp_path) -> None:
    data_dir = str(tmp_path)
    user_dir = os.path.join(data_dir, "users", "test_user")
    os.makedirs(user_dir, exist_ok=True)
    
    # Write profile with the current model, dimension and version
    profile = {
        "user": "test_user",
        "embeddings": [
            [1.0] + [0.0] * (EMBEDDING_DIMENSION - 1)
        ],
        "embedding_model": EMBEDDING_MODEL,
        "embedding_dimension": EMBEDDING_DIMENSION,
        "embedding_version": EMBEDDING_VERSION,
    }
    with open(os.path.join(user_dir, "profile.json"), "w") as f:
        json.dump(profile, f)
        
    matcher = EmbeddingMatcher(data_dir=data_dir)
    
    query = np.array([1.0] + [0.0] * (EMBEDDING_DIMENSION - 1), dtype=np.float32)
    user, sim = matcher.match_face(query, threshold=0.7)
    assert user == "test_user"
    assert sim > 0.99


def test_is_profile_compatible() -> None:
    profile = {
        "embedding_model": EMBEDDING_MODEL,
        "embedding_dimension": EMBEDDING_DIMENSION,
        "embedding_version": EMBEDDING_VERSION,
    }
    assert is_profile_compatible(profile)
    assert not is_profile_compatible({**profile, "embedding_model": "FaceNet-512"})
    assert not is_profile_compatible({})


@pytest.mark.skipif(
    not (MODELS_DIR / RECOGNIZER_MODEL_FILE).exists(),
    reason="SFace model not downloaded (run scripts/download_models.py)",
)
def test_real_model_extracts_normalized_embedding() -> None:
    extractor = EmbeddingExtractor()
    face_crop = np.random.default_rng(0).integers(0, 255, (150, 130, 3), dtype=np.uint8)

    emb = extractor.extract_embedding(face_crop)

    assert emb.shape == (EMBEDDING_DIMENSION,)
    assert abs(float(np.linalg.norm(emb)) - 1.0) < 1e-5
