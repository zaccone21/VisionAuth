"""Unit tests for the recognition embeddings module."""

import numpy as np
import os
import json
import pytest
from unittest.mock import patch, MagicMock
from visionauth.recognition.recognition_embeddings import (
    EmbeddingExtractor,
    EmbeddingMatcher,
    cosine_similarity,
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


@patch("cv2.dnn.readNetFromONNX")
def test_incorrect_dimension(mock_read_net, tmp_path) -> None:
    model_file = tmp_path / "dummy.onnx"
    model_file.write_text("dummy content")
    
    mock_net = MagicMock()
    # Returns a 128-dimensional output instead of 512
    mock_net.forward.return_value = np.zeros((1, 128), dtype=np.float32)
    mock_read_net.return_value = mock_net
    
    with pytest.raises(RuntimeError) as excinfo:
        EmbeddingExtractor(model_path=str(model_file))
    assert "validation failed" in str(excinfo.value)


@patch("cv2.dnn.readNetFromONNX")
def test_nan_inf_embeddings(mock_read_net, tmp_path) -> None:
    model_file = tmp_path / "dummy.onnx"
    model_file.write_text("dummy content")
    
    # 1. Test NaN
    mock_net = MagicMock()
    nan_arr = np.zeros((1, 512), dtype=np.float32)
    nan_arr[0, 0] = np.nan
    mock_net.forward.return_value = nan_arr
    mock_read_net.return_value = mock_net
    
    with pytest.raises(RuntimeError) as excinfo:
        EmbeddingExtractor(model_path=str(model_file))
    assert "validation failed" in str(excinfo.value)
    
    # 2. Test Inf
    inf_arr = np.zeros((1, 512), dtype=np.float32)
    inf_arr[0, 0] = np.inf
    mock_net.forward.return_value = inf_arr
    
    with pytest.raises(RuntimeError) as excinfo:
        EmbeddingExtractor(model_path=str(model_file))
    assert "validation failed" in str(excinfo.value)


def test_incompatible_profile(tmp_path) -> None:
    data_dir = str(tmp_path)
    user_dir = os.path.join(data_dir, "users", "test_user")
    os.makedirs(user_dir, exist_ok=True)
    
    # Write a profile with wrong dimension (128)
    profile = {
        "user": "test_user",
        "embeddings": [np.zeros(128).tolist()],
        "embedding_model": "FaceNet-512",
        "embedding_dimension": 128,  # Incompatible
        "embedding_version": 2
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
    
    # Write profile with version 1 instead of 2
    profile = {
        "user": "test_user",
        "embeddings": [np.zeros(512).tolist()],
        "embedding_model": "FaceNet-512",
        "embedding_dimension": 512,
        "embedding_version": 1  # Incompatible version
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
    
    # Write profile with version 2 and 512D
    profile = {
        "user": "test_user",
        "embeddings": [
            [1.0] + [0.0]*511
        ],
        "embedding_model": "FaceNet-512",
        "embedding_dimension": 512,
        "embedding_version": 2
    }
    with open(os.path.join(user_dir, "profile.json"), "w") as f:
        json.dump(profile, f)
        
    matcher = EmbeddingMatcher(data_dir=data_dir)
    
    query = np.array([1.0] + [0.0]*511, dtype=np.float32)
    user, sim = matcher.match_face(query, threshold=0.7)
    assert user == "test_user"
    assert sim > 0.99
