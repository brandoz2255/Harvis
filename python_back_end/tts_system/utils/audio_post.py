"""
Audio Post-Processing Utilities
Provides mastering chain for podcast audio:
- High-pass filtering
- compression/limiting
- Loudness normalization
"""

import numpy as np
import scipy.signal
import logging

logger = logging.getLogger(__name__)

def butter_highpass(cutoff: float, fs: int, order: int = 5):
    """Design a highpass filter"""
    nyq = 0.5 * fs
    normal_cutoff = cutoff / nyq
    b, a = scipy.signal.butter(order, normal_cutoff, btype='high', analog=False)
    return b, a

def highpass_filter(data: np.ndarray, cutoff: float, fs: int, order: int = 5) -> np.ndarray:
    """Apply highpass filter to audio data"""
    try:
        b, a = butter_highpass(cutoff, fs, order=order)
        y = scipy.signal.filtfilt(b, a, data)
        return y.astype(np.float32)
    except Exception as e:
        logger.warning(f"Highpass filter failed: {e}")
        return data

def limiter(data: np.ndarray, threshold_db: float = -1.0) -> np.ndarray:
    """
    Hard limiter to prevent clipping
    
    Args:
        data: Audio data (float32)
        threshold_db: Threshold in dB (default -1.0)
    """
    threshold = 10 ** (threshold_db / 20)
    return np.clip(data, -threshold, threshold)

def normalize_loudness(data: np.ndarray, target_db: float = -3.0) -> np.ndarray:
    """
    Simple peak normalization
    
    Args:
        data: Audio data (float32)
        target_db: Target peak level in dB
    """
    peak = np.max(np.abs(data))
    if peak == 0:
        return data
        
    target = 10 ** (target_db / 20)
    gain = target / peak
    
    # Don't apply extreme gain
    if gain > 10.0:  # Cap at +20dB
        gain = 10.0
        
    return data * gain

def process_podcast_master(
    audio_data: np.ndarray, 
    sample_rate: int,
    norm_target_db: float = -1.0
) -> np.ndarray:
    """
    Apply mastering chain to podcast audio
    
    1. High-pass filter (80Hz) to remove rumble
    2. Peak normalization/Limiting
    """
    # Ensure float32
    if audio_data.dtype != np.float32:
        audio_data = audio_data.astype(np.float32)
        
    # 1. High-pass filter (80 Hz)
    # Removes low-end rumble sometimes produced by RVC
    processed = highpass_filter(audio_data, cutoff=80.0, fs=sample_rate)
    
    # 2. Normalize/Limit
    processed = normalize_loudness(processed, target_db=norm_target_db)
    processed = limiter(processed, threshold_db=norm_target_db)
    
    return processed
