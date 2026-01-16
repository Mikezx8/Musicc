import os
import sys
import json
import time
import threading
import urllib.parse
import logging
import subprocess
import base64
import mimetypes
import io
from http.server import HTTPServer, SimpleHTTPRequestHandler
from socketserver import ThreadingMixIn

# Third-party imports
import requests
import yt_dlp
from mutagen.mp3 import MP3
from mutagen.id3 import ID3, APIC, TIT2, TPE1, TALB, TCON

# -----------------------------------------------------------------------------
# CONFIGURATION
# -----------------------------------------------------------------------------

CLIENT_ID = "630c521d6a5d4a269db2aeadc3255f08"
CLIENT_SECRET = "a388ba1022c84e9aad939ae6a96652b0"
REDIRECT_URI = "https://musicc-oyb7.onrender.com//callback"
PORT = 5000
DOWNLOAD_DIR = os.path.join(os.getcwd(), "music_library")
STREAM_CACHE_FILE = os.path.join(os.getcwd(), "stream_cache.json")

os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# Global State
auth_state = {
    "access_token": None,
    "refresh_token": None,
    "expires_at": 0
}

# Lock for thread-safe file operations
stream_cache_lock = threading.Lock()

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# -----------------------------------------------------------------------------
# FRONTEND (HTML/CSS/JS)
# -----------------------------------------------------------------------------

HTML_CONTENT = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>PyMusic - Stream & Download</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg: #0a0a0a;
            --surface: #141414;
            --surface-hover: #1f1f1f;
            --surface-light: #2a2a2a;
            --primary: #ffffff;
            --primary-dim: #e0e0e0;
            --text: #ffffff;
            --text-sub: #888888;
            --text-muted: #555555;
            --accent: #ffffff;
            --border: #252525;
            --success: #4ade80;
            --error: #f87171;
            --warning: #fbbf24;
        }

        * { 
            box-sizing: border-box; 
            margin: 0; 
            padding: 0; 
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
            -webkit-tap-highlight-color: transparent;
        }

        /* Custom Scrollbar */
        ::-webkit-scrollbar { width: 6px; height: 6px; }
        ::-webkit-scrollbar-track { background: var(--bg); }
        ::-webkit-scrollbar-thumb { background: var(--surface-light); border-radius: 10px; transition: background 0.3s; }
        ::-webkit-scrollbar-thumb:hover { background: var(--text-sub); }
        * { scrollbar-width: thin; scrollbar-color: var(--surface-light) var(--bg); }

        html, body { 
            background-color: var(--bg); 
            color: var(--text); 
            height: 100%; 
            overflow: hidden; 
        }
        body { display: flex; flex-direction: column; }

        /* Header */
        header { 
            background: rgba(10,10,10,0.95);
            padding: 0.75rem 1rem; 
            display: flex; 
            justify-content: space-between; 
            align-items: center; 
            border-bottom: 1px solid var(--border);
            backdrop-filter: blur(20px);
            -webkit-backdrop-filter: blur(20px);
            position: relative; z-index: 50;
            flex-shrink: 0;
        }

        .logo { font-size: 1.1rem; font-weight: 800; display: flex; align-items: center; gap: 10px; letter-spacing: -0.5px; cursor: pointer; }
        .logo-icon { width: 32px; height: 32px; display: flex; align-items: center; justify-content: center; }

        nav { display: flex; align-items: center; gap: 0.25rem; }

        .nav-btn { 
            background: none; border: none; color: var(--text-sub); cursor: pointer; font-weight: 500; 
            font-size: 0.85rem; padding: 0.5rem 0.75rem; border-radius: 8px; transition: all 0.2s ease;
        }
        .nav-btn:hover { color: var(--text); background: var(--surface); }

        .btn-primary { 
            background: var(--primary); color: var(--bg); padding: 0.5rem 1.25rem; border-radius: 50px; 
            border: none; cursor: pointer; font-weight: 600; font-size: 0.85rem; transition: all 0.2s ease; margin-left: 0.5rem;
        }
        .btn-primary:hover { transform: scale(1.02); box-shadow: 0 4px 20px rgba(255,255,255,0.15); }

        /* Main Content */
        main { 
            flex: 1; 
            overflow-y: auto; 
            padding: 1.5rem; 
            max-width: 1400px; 
            margin: 0 auto; 
            width: 100%;
            position: relative;
            z-index: 1;
        }

        .section-title { margin-bottom: 1rem; font-size: 1.35rem; font-weight: 700; letter-spacing: -0.5px; }

        /* Quick Links Grid */
        .quick-links { display: grid; grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); gap: 0.75rem; margin-bottom: 2rem; }
        .quick-card { 
            background: var(--surface); border-radius: 12px; padding: 1rem; display: flex; align-items: center; 
            gap: 1rem; cursor: pointer; transition: all 0.25s ease; border: 1px solid transparent;
        }
        .quick-card:hover { background: var(--surface-hover); transform: translateY(-2px); border-color: var(--border); }
        .quick-icon { font-size: 1.4rem; filter: grayscale(100%); }
        .quick-card span:last-child { font-weight: 600; font-size: 0.9rem; }

        /* Genre Grid */
        .genre-grid { 
            display: grid; 
            grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); 
            gap: 0.75rem; 
            margin-bottom: 2rem; 
        }

        .genre-card {
            position: relative;
            height: 100px;
            border-radius: 12px;
            overflow: hidden;
            cursor: pointer;
            transition: transform 0.2s ease, box-shadow 0.2s ease;
        }

        .genre-card:hover { transform: scale(1.02); box-shadow: 0 8px 20px rgba(0,0,0,0.4); z-index: 2; }

        .genre-bg {
            position: absolute;
            top: 0; left: 0; width: 100%; height: 100%;
            background-size: cover;
            background-position: center;
            transition: transform 0.4s ease;
        }
        .genre-card:hover .genre-bg { transform: scale(1.1); }

        .genre-overlay {
            position: absolute;
            top: 0; left: 0; width: 100%; height: 100%;
            background: linear-gradient(0deg, rgba(0,0,0,0.8) 0%, rgba(0,0,0,0.2) 100%);
            display: flex;
            align-items: flex-end;
            padding: 0.75rem;
        }
        .genre-name { color: white; font-weight: 700; font-size: 0.95rem; text-shadow: 0 2px 4px rgba(0,0,0,0.5); }

        /* Search */
        .search-container { margin-bottom: 1.5rem; display: flex; gap: 10px; }
        #search-input { 
            flex: 1; padding: 0.85rem 1rem; border-radius: 12px; border: 1px solid var(--border); 
            background: var(--surface); color: var(--text); font-size: 0.95rem; transition: all 0.2s ease;
        }
        #search-input:focus { outline: none; border-color: var(--text-sub); background: var(--surface-hover); }
        #search-input::placeholder { color: var(--text-muted); }

        /* Cards Grid */
        .card-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); gap: 1rem; }
        .card { 
            background: var(--surface); padding: 1rem; border-radius: 12px; cursor: pointer; 
            transition: all 0.25s ease; border: 1px solid transparent;
        }
        .card:hover { background: var(--surface-hover); transform: translateY(-4px); box-shadow: 0 12px 40px rgba(0,0,0,0.4); border-color: var(--border); }
        .card img { width: 100%; aspect-ratio: 1; object-fit: cover; border-radius: 8px; margin-bottom: 0.75rem; background-color: var(--surface-light); }
        .card-title { font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; font-size: 0.9rem; margin-bottom: 0.25rem; }
        .card-sub { color: var(--text-sub); font-size: 0.8rem; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
        
        /* Play Count Badge */
        .play-count {
            position: absolute;
            top: 10px;
            right: 10px;
            background: rgba(0, 0, 0, 0.7);
            backdrop-filter: blur(4px);
            color: white;
            padding: 4px 8px;
            border-radius: 12px;
            font-size: 0.7rem;
            font-weight: 700;
            pointer-events: none;
            box-shadow: 0 2px 8px rgba(0,0,0,0.4);
            opacity: 1;
        }

        /* List Items */
        .list-group { display: flex; flex-direction: column; gap: 0.35rem; position: relative; z-index: 2; }
        .list-item { 
            display: flex; align-items: center; background: var(--surface); padding: 0.6rem 0.75rem; 
            border-radius: 10px; transition: all 0.2s ease; border: 1px solid transparent;
            position: relative;
            z-index: 2;
        }
        .list-item:hover { background: var(--surface-hover); }
        .list-item.playing { background: rgba(255, 255, 255, 0.08); border: 1px solid var(--text-sub); }
        .list-item img { width: 44px; height: 44px; margin-right: 0.75rem; border-radius: 6px; background-color: var(--surface-light); object-fit: cover; flex-shrink: 0; }
        
        .list-info { flex: 1; min-width: 0; display: flex; align-items: center; gap: 10px; cursor: pointer; padding: 4px; border-radius: 6px; }
        .list-info:hover { background: rgba(255,255,255,0.03); }
        .list-info > div:last-child { overflow: hidden; }
        .list-info > div:last-child > div:first-child { font-weight: 500; font-size: 0.9rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        
        .list-meta { color: var(--text-sub); font-size: 0.8rem; margin-right: 0.75rem; min-width: 36px; text-align: right; flex-shrink: 0; }
        .list-actions { display: flex; gap: 0.4rem; align-items: center; flex-shrink: 0; }

        .action-btn { 
            background: none; border: 1px solid var(--text-muted); color: var(--text-sub); border-radius: 50px; 
            padding: 0.3rem 0.75rem; cursor: pointer; font-size: 0.75rem; font-weight: 500; transition: all 0.2s ease; 
        }
        .action-btn:hover { border-color: var(--text); color: var(--text); background: rgba(255,255,255,0.05); }
        .dl-btn { border-color: var(--text-sub); color: var(--text-sub); }
        .dl-btn:hover { background: var(--text); color: var(--bg); border-color: var(--text); }
        .dl-btn.downloading { opacity: 0.5; cursor: wait; }

        #detail-view-wrapper {
            position: relative;
            margin: -1.5rem;
            margin-bottom: 1.5rem;
            padding-top: 1.5rem;
            padding-bottom: 6rem;
            overflow: visible;
            z-index: 0;
        }

        #detail-tracks, #detail-albums {
            position: relative;
            z-index: 2;
        }

        #detail-bg-layer {
            position: absolute;
            top: 0; left: 0; 
            width: 100%; 
            height: 500px;
            background-size: cover;
            background-position: center;
            filter: blur(80px) brightness(0.3);
            z-index: -1;
            mask-image: linear-gradient(to bottom, 
                black 0%, 
                black 40%, 
                rgba(0,0,0,0.8) 60%, 
                rgba(0,0,0,0.4) 80%, 
                transparent 100%);
            -webkit-mask-image: linear-gradient(to bottom, 
                black 0%, 
                black 40%, 
                rgba(0,0,0,0.8) 60%, 
                rgba(0,0,0,0.4) 80%, 
                transparent 100%);
            transition: background-image 0.5s ease;
            pointer-events: none;
        }

        #detail-header {
            position: relative;
            z-index: 2;
            display: flex; 
            gap: 1.5rem; 
            align-items: flex-end;
            padding: 0 1.5rem;
        }

        .detail-back-btn {
            position: absolute;
            top: 20px;
            left: 20px;
            z-index: 100;
            background: rgba(0,0,0,0.6);
            backdrop-filter: blur(10px);
            border: 1px solid rgba(255,255,255,0.1);
            color: white;
            padding: 0.5rem 1rem;
            border-radius: 20px;
            font-size: 0.9rem;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s ease;
            display: flex;
            align-items: center;
            gap: 6px;
        }
        .detail-back-btn:hover {
            background: rgba(255,255,255,0.2);
            transform: translateX(-2px);
        }

        #view-detail #artist-tabs,
        #view-detail #detail-title,
        #view-detail #download-all-btn {
            position: relative;
            z-index: 10;
        }

        /* Footer Player */
        footer { 
            background: linear-gradient(180deg, var(--surface) 0%, rgba(10,10,10,1) 100%);
            border-top: 1px solid var(--border); 
            padding: 0;
            display: flex; 
            align-items: center; 
            justify-content: space-between; 
            height: 90px; 
            z-index: 100; 
            width: 100%;
            cursor: pointer; 
            user-select: none;
            flex-shrink: 0;
        }
        
        .footer-padding {
            width: 100%;
            height: 100%;
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 0 1.5rem;
        }

        .player-info { display: flex; align-items: center; gap: 1rem; width: 30%; min-width: 150px; pointer-events: none; }
        #footer-cover { pointer-events: auto; }

        #footer-cover { width: 64px; height: 64px; border-radius: 12px; background: var(--surface-light); object-fit: cover; box-shadow: 0 4px 12px rgba(0,0,0,0.4); transition: transform 0.2s;}
        #footer-cover:hover { transform: scale(1.05); }

        .player-text { display: flex; flex-direction: column; overflow: hidden; justify-content: center; }
        #footer-title { font-weight: 600; font-size: 0.95rem; color: var(--text); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
        #footer-artist { font-size: 0.8rem; color: var(--text-sub); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

        .player-center { display: flex; flex-direction: column; align-items: center; justify-content: center; width: 40%; max-width: 600px; gap: 8px; pointer-events: none;}
        .player-buttons { display: flex; align-items: center; justify-content: center; gap: 1rem; pointer-events: auto; }

        .control-btn {
            background: none; border: none; color: var(--text-sub); font-size: 1.4rem; cursor: pointer; 
            transition: all 0.2s ease; display: flex; align-items: center; justify-content: center;
            width: 44px; height: 44px; border-radius: 50%;
        }
        .control-btn:hover { color: var(--text); background: var(--surface-hover); }
        
        .play-pause-btn {
            background: var(--text); color: var(--bg); border-radius: 50%; width: 56px; height: 56px; 
            font-size: 1.4rem; display: flex; align-items: center; justify-content: center; transition: all 0.2s ease;
            box-shadow: 0 4px 12px rgba(0,0,0,0.3);
            position: relative; /* For spinner positioning */
        }
        .play-pause-btn:hover { transform: scale(1.08); box-shadow: 0 8px 24px rgba(255,255,255,0.25); }

        /* Progress Container Styles - Fixed Height for Thumb Visibility */
        .progress-container {
            width: 100%; 
            display: flex; 
            align-items: center; 
            gap: 12px; 
            font-size: 0.75rem; 
            color: var(--text-muted); 
            pointer-events: auto; 
            height: 30px; /* Increased height to accommodate thumb */
            position: relative; 
        }
        
        input[type=range].progress-slider {
            -webkit-appearance: none;
            background: transparent;
            width: 100%;
            cursor: pointer;
            height: 100%; /* Fill container */
            border-radius: 2px;
            position: relative;
            z-index: 2;
            margin: 0;
        }

        .progress-fill {
            position: absolute;
            top: 50%; 
            left: 0;
            height: 4px; /* Track visual height */
            transform: translateY(-50%);
            background: var(--text-sub);
            width: 0%;
            border-radius: 2px;
            pointer-events: none;
            transition: width 0.1s linear;
            z-index: 1;
        }

        input[type=range].progress-slider::-webkit-slider-runnable-track {
            width: 100%;
            height: 4px;
            cursor: pointer;
            background: transparent;
            border-radius: 2px;
        }

        input[type=range].progress-slider::-webkit-slider-thumb {
            height: 20px; 
            width: 20px; 
            border-radius: 50%; 
            background: var(--text); 
            cursor: pointer;
            -webkit-appearance: none; 
            margin-top: -8px; /* Centers thumb on track (20px - 4px)/2 */
            opacity: 1; 
            transition: all 0.2s ease; 
            box-shadow: 0 0 0 1px rgba(0,0,0,0.3);
        }

        input[type=range].progress-slider:hover::-webkit-slider-thumb {
            transform: scale(1.1); 
        }

        input[type=range].progress-slider:active::-webkit-slider-thumb { 
            transform: scale(1.2); 
        }

        /* Firefox */
        input[type=range].progress-slider::-moz-range-track {
            width: 100%;
            height: 4px;
            cursor: pointer;
            background: transparent;
            border-radius: 2px;
        }

        input[type=range].progress-slider::-moz-range-thumb {
            height: 20px;
            width: 20px;
            border-radius: 50%;
            background: var(--text);
            cursor: pointer;
            border: none;
            box-shadow: 0 0 0 1px rgba(0,0,0,0.3);
            transition: all 0.2s ease;
        }

        input[type=range].progress-slider:hover::-moz-range-thumb {
            transform: scale(1.1);
        }

        input[type=range].progress-slider:active::-moz-range-thumb {
            transform: scale(1.2);
        }

        .player-right { display: flex; align-items: center; justify-content: flex-end; width: 30%; min-width: 120px; gap: 1rem; pointer-events: auto;}
        
        /* Volume */
        .volume-container { position: relative; display: flex; align-items: center; }
        .volume-dropdown {
            position: absolute; 
            bottom: 100%;
            right: 0;
            margin-bottom: 10px;
            background: var(--surface); 
            padding: 12px 8px; 
            border-radius: 12px;
            width: 40px; 
            height: 120px; 
            display: flex; 
            justify-content: center; 
            opacity: 0; 
            pointer-events: none; 
            transition: all 0.2s ease; 
            box-shadow: 0 8px 32px rgba(0,0,0,0.5); 
            border: 1px solid var(--border);
            z-index: 1000;
        }
        .volume-dropdown.show { 
            opacity: 1; 
            pointer-events: auto; 
        }
        input[type=range][orient=vertical] { writing-mode: bt-lr; -webkit-appearance: slider-vertical; width: 8px; height: 90px; padding: 0 5px; }
        .status-msg { color: var(--text-sub); font-size: 0.8rem; text-align: right; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 120px; }

        /* Fullscreen Player */
        #fullscreen-player {
            position: fixed; top: 0; left: 0; width: 100vw; height: 100vh;
            background: #000;
            z-index: 2000; display: none; 
            overflow-y: scroll; 
            scroll-snap-type: y mandatory; 
            -webkit-overflow-scrolling: touch;
        }

        #fullscreen-player::-webkit-scrollbar { display: none; }
        #fullscreen-player { -ms-overflow-style: none; scrollbar-width: none; }

        #fullscreen-player.active { display: block; }

        .fs-snap-section {
            height: 100vh;
            width: 100%;
            display: flex;
            flex-direction: column;
            position: relative;
            overflow: hidden;
            scroll-snap-align: start; 
            flex-shrink: 0;
        }

        /* Section 1: Music Controls */
        .fs-header {
            position: absolute; top: 0; left: 0; width: 100%;
            display: flex; justify-content: space-between; align-items: center; 
            padding: 1.5rem; z-index: 10;
            background: linear-gradient(180deg, rgba(0,0,0,0.6) 0%, transparent 100%);
            pointer-events: none; 
        }
        
        .fs-header-right {
            display: flex;
            align-items: center;
            gap: 1rem;
            pointer-events: auto;
        }

        .close-fs { 
            font-size: 1.5rem; cursor: pointer; color: white; transition: all 0.2s ease; width: 44px; height: 44px; 
            display: flex; align-items: center; justify-content: center; border-radius: 50%; background: rgba(0,0,0,0.4);
            backdrop-filter: blur(4px);
        }
        .close-fs:hover { background: rgba(255,255,255,0.1); }

        .fs-content-center {
            flex: 1;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            padding: 2rem;
            width: 100%;
            gap: 1.5rem;
            transition: transform 0.3s cubic-bezier(0.2, 0.8, 0.2, 1);
            position: relative;
            z-index: 5;
            pointer-events: none; 
        }

        /* Enable pointer events on interactive children */
        .fs-content-center > * {
            pointer-events: auto;
        }

        /* Desktop Download Button (At bottom) */
        .fs-download-btn-desktop {
            background: var(--surface);
            border: 1px solid var(--border);
            color: var(--text);
            padding: 0.75rem 1.5rem;
            border-radius: 50px;
            cursor: pointer;
            font-weight: 600;
            font-size: 0.9rem;
            transition: all 0.2s ease;
            margin-top: 1rem;
            pointer-events: auto;
            z-index: 20;
        }
        .fs-download-btn-desktop:hover {
            background: var(--text);
            color: var(--bg);
            border-color: var(--text);
        }

        /* Mobile Download Button (Top Right, where Volume is) */
        .fs-download-btn-mobile {
            background: rgba(0,0,0,0.4);
            backdrop-filter: blur(4px);
            border: 1px solid rgba(255,255,255,0.1);
            color: white;
            width: 44px;
            height: 44px;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            cursor: pointer;
            font-size: 1.2rem;
            transition: all 0.2s ease;
        }
        .fs-download-btn-mobile:hover {
            background: rgba(255,255,255,0.1);
        }

        .fs-cover { 
            width: 320px; height: 320px; box-shadow: 0 25px 50px -12px rgba(0,0,0,0.8); object-fit: cover; border-radius: 16px;
            flex-shrink: 0;
            max-width: 80vw;
            max-height: 50vh;
            pointer-events: auto;
        }

        .fs-info { text-align: center; width: 100%; max-width: 600px; pointer-events: none; }
        .fs-title { font-size: 2.2rem; font-weight: 800; margin-bottom: 0.5rem; letter-spacing: -0.5px; }
        .fs-artist { font-size: 1.3rem; color: var(--text-sub); }

        /* Fullscreen Progress */
        .fs-progress-container { 
            width: 100%; display: flex; align-items: center; gap: 12px; 
            color: var(--text-sub); font-size: 0.95rem;
            height: 40px; 
            padding: 0 1rem;
            pointer-events: auto; 
        }

        .fs-player-buttons { display: flex; align-items: center; justify-content: center; gap: 2rem; margin-top: 1rem; pointer-events: auto;}
        .fs-control-btn {
            background: none; border: none; color: var(--text-sub); font-size: 1.8rem; cursor: pointer; 
            transition: all 0.2s ease; display: flex; align-items: center; justify-content: center;
            width: 50px; height: 50px; border-radius: 50%;
        }
        .fs-control-btn:hover { color: var(--text); background: rgba(255,255,255,0.1); }
        .fs-play-btn {
            width: 80px; height: 80px; border-radius: 50%; background: var(--text); border: none; 
            display: flex; align-items: center; justify-content: center; font-size: 2rem; cursor: pointer; 
            transition: all 0.2s ease; color: var(--bg);
            box-shadow: 0 8px 30px rgba(255,255,255,0.3);
            position: relative; /* For spinner positioning */
        }
        .fs-play-btn:hover { transform: scale(1.05); box-shadow: 0 12px 40px rgba(255,255,255,0.4); }

        .fs-volume-control {
            display: flex;
            align-items: center;
            gap: 10px;
            pointer-events: auto;
        }

        .scroll-hint {
            position: absolute; bottom: 2rem; left: 50%; transform: translateX(-50%);
            color: var(--text-sub); font-size: 0.8rem; display: flex; flex-direction: column; align-items: center; gap: 5px;
            opacity: 0.6; animation: bounce 2s infinite; pointer-events: none;
            z-index: 1;
        }
        @keyframes bounce { 0%, 20%, 50%, 80%, 100% {transform:translate(-50%, 0);} 40% {transform:translate(-50%, -10px);} 60% {transform:translate(-50%, -5px);} }

        /* Section 2: Lyrics & Queue */
        .fs-details-section {
            background: var(--bg);
            padding: 2rem;
            display: flex;
            align-items: center;
            justify-content: center;
            transform: none; 
        }
        
        .fs-grid-layout {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 2rem;
            width: 100%;
            max-width: 1200px;
            height: 70vh;
        }

        .fs-panel { 
            background: var(--surface); 
            border-radius: 20px; 
            padding: 1.5rem; 
            display: flex; 
            flex-direction: column; 
            overflow: hidden;
            border: 1px solid var(--border);
            height: 100%; 
            width: 100%;
        }

        .panel-header { 
            font-size: 0.9rem; font-weight: 700; margin-bottom: 1rem; padding-bottom: 0.5rem;
            border-bottom: 1px solid var(--border); text-transform: uppercase; letter-spacing: 1.5px; 
            color: var(--text-sub); flex-shrink: 0;
        }

        .panel-content-scroll {
            overflow-y: auto;
            flex: 1;
            padding-right: 5px;
        }
        .panel-content-scroll::-webkit-scrollbar { width: 4px; }
        .panel-content-scroll::-webkit-scrollbar-thumb { background: var(--surface-light); border-radius: 4px; }

        .lyrics-content { 
            display: flex; align-items: center; justify-content: center; color: var(--text-muted); 
            font-style: italic; font-size: 1rem; text-align: center; height: 100%;
        }

        .queue-list { display: flex; flex-direction: column; gap: 0.5rem; }
        .queue-item { 
            display: flex; align-items: center; gap: 10px; padding: 8px 12px; border-radius: 12px; cursor: pointer; 
            transition: all 0.2s ease; background: rgba(255,255,255,0.03);
        }
        .queue-item:hover { background: rgba(255,255,255,0.08); }
        .queue-item img { width: 40px; height: 40px; border-radius: 8px; object-fit: cover; }
        .queue-info { flex: 1; overflow: hidden; }
        .queue-info div { font-size: 0.9rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--text); font-weight: 500; }
        .queue-info span { font-size: 0.8rem; color: var(--text-sub); }
        .queue-duration { color: var(--text-muted); font-size: 0.8rem; font-weight: 600; }

        /* Modal */
        .modal-overlay {
            position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.85); z-index: 1000;
            display: none; justify-content: center; align-items: center; backdrop-filter: blur(8px);
            -webkit-backdrop-filter: blur(8px);
        }
        .modal-content {
            background: var(--surface); padding: 1.5rem; border-radius: 16px; width: 92%; max-width: 700px; 
            max-height: 80vh; overflow-y: auto; position: relative; animation: modalSlideIn 0.3s ease-out; border: 1px solid var(--border);
        }
        @keyframes modalSlideIn { from { transform: translateY(-30px) scale(0.95); opacity: 0; } to { transform: translateY(0) scale(1); opacity: 1; } }
        .close-modal { position: absolute; top: 12px; right: 16px; font-size: 1.25rem; cursor: pointer; color: var(--text-sub); transition: all 0.2s ease; width: 36px; height: 36px; display: flex; align-items: center; justify-content: center; border-radius: 50%; }
        .close-modal:hover { color: var(--text); background: var(--surface-hover); }

        .tabs { display: flex; gap: 0.5rem; margin-bottom: 1.25rem; border-bottom: 1px solid var(--border); padding-bottom: 0.5rem; position: relative; z-index: 2;}
        .tab { cursor: pointer; padding: 0.5rem 1rem; border-radius: 8px; color: var(--text-sub); font-weight: 500; font-size: 0.9rem; transition: all 0.2s ease; }
        .tab:hover { color: var(--text); background: var(--surface); }
        .tab.active { color: var(--text); background: var(--surface-hover); }

        .hidden { display: none !important; }
        .spinner { border: 2px solid var(--surface-light); border-top: 2px solid var(--text); border-radius: 50%; width: 28px; height: 28px; animation: spin 0.8s linear infinite; margin: 2rem auto; }
        @keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }

        /* Equalizer */
        .equalizer { display: flex; align-items: flex-end; gap: 2px; height: 16px; width: 14px; flex-shrink: 0; }
        .bar { width: 3px; background-color: var(--text); animation: bounce 1s infinite ease-in-out; border-radius: 2px; }
        .bar:nth-child(1) { animation-delay: 0.0s; }
        .bar:nth-child(2) { animation-delay: 0.2s; }
        .bar:nth-child(3) { animation-delay: 0.4s; }
        .paused .bar { animation-play-state: paused; height: 3px; transition: height 0.2s; }
        @keyframes bounce { 0%, 100% { height: 3px; } 50% { height: 16px; } }

        .text-sub { color: var(--text-sub); }

        /* Loading Spinner for Buttons */
        .play-spinner {
            border: 2px solid rgba(0,0,0,0.1);
            border-top: 2px solid #000;
            border-radius: 50%;
            width: 24px;
            height: 24px;
            animation: spin 1s linear infinite;
            position: absolute;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
            display: none;
            pointer-events: none;
        }

/* Mobile Styles */
@media (max-width: 768px) {
    header { padding: 0.6rem 0.75rem; }
    .logo { font-size: 1rem; }
    .nav-btn { padding: 0.4rem 0.5rem; font-size: 0.75rem; }
    .btn-primary { padding: 0.4rem 0.9rem; font-size: 0.75rem; }
    main { padding: 1rem; }
    .section-title { font-size: 1.15rem; }
    .quick-links { grid-template-columns: repeat(2, 1fr); gap: 0.5rem; }
    .card-grid { grid-template-columns: repeat(auto-fill, minmax(130px, 1fr)); gap: 0.75rem; }
    .list-meta { display: none; }
    .action-btn { padding: 0.25rem 0.5rem; font-size: 0.65rem; }
    
    /* Footer Mobile */
    footer { 
        height: 80px;
        padding: 0; 
    }
    
    .footer-padding { 
        padding: 0.75rem 1rem; 
        gap: 1rem;
        flex-direction: row;
        justify-content: space-between;
        align-items: center;
    }
    
    .player-info { 
        width: auto;
        flex: 1;
        justify-content: flex-start; 
        padding: 0;
        pointer-events: none;
    }
    #footer-cover { 
        width: 50px; 
        height: 50px;
        pointer-events: auto;
    }
    #footer-title { font-size: 0.85rem; }
    #footer-artist { font-size: 0.75rem; }
    
    .player-center { 
        display: none;
    }
    
    .player-right { 
        display: flex;
        align-items: center;
        gap: 0.75rem;
        width: auto;
        min-width: auto;
        pointer-events: auto;
    }
    
    .volume-container { display: none; }
    .status-msg { display: none; }
    
    #mobile-download-btn {
        display: flex !important;
        background: var(--surface);
        border: 1px solid var(--border);
        color: var(--text);
        width: 50px;
        height: 50px;
        border-radius: 50%;
        font-size: 1.2rem;
        cursor: pointer;
        transition: all 0.2s ease;
        align-items: center;
        justify-content: center;
    }
    #mobile-download-btn:active {
        background: var(--text);
        color: var(--bg);
    }
    
    #mobile-play-btn {
        display: flex !important;
        background: var(--text);
        color: var(--bg);
        width: 50px;
        height: 50px;
        border-radius: 50%;
        font-size: 1.2rem;
        cursor: pointer;
        transition: all 0.2s ease;
        align-items: center;
        justify-content: center;
        box-shadow: 0 4px 12px rgba(0,0,0,0.3);
        position: relative; /* For spinner positioning */
    }
    #mobile-play-btn:active {
        transform: scale(0.95);
    }

    /* Fullscreen Mobile Specifics */
    .fs-grid-layout { grid-template-columns: 1fr; grid-template-rows: 1fr 1fr; height: auto; gap: 1rem; }
    .fs-panel { height: 40vh; }

    .fs-cover { width: 75vw; height: 75vw; margin: 1rem auto; }
    .fs-title { font-size: 1.6rem; }
    .fs-artist { font-size: 1.1rem; }
    .fs-play-btn { width: 70px; height: 70px; }
    
    /* Hide Volume in Mobile Fullscreen */
    .fs-volume-control { display: none !important; }
    
    /* Show Mobile Download Button (Top Right) */
    .fs-download-btn-mobile {
        display: flex !important;
    }
    
    /* Hide Desktop Download Button (Bottom Center) */
    .fs-download-btn-desktop {
        display: none !important;
    }

    /* Detail View Mobile */
    #detail-header { flex-direction: column; align-items: center; text-align: center; gap: 1rem; }
    #detail-header img { width: 140px !important; height: 140px !important; }
    #detail-header h1 { font-size: 1.5rem !important; }
    
    .modal-content { width: 95%; padding: 1rem; }
}

/* Desktop Styles specific to Fullscreen */
@media (min-width: 769px) {
    /* Hide Mobile Download Button */
    .fs-download-btn-mobile {
        display: none !important;
    }
    
    /* Show Desktop Download Button */
    .fs-download-btn-desktop {
        display: inline-block !important;
    }
}
    </style>
</head>
<body>

<header>
    <div class="logo" onclick="loadView('home')">
        <div class="logo-icon">
            <svg width="28" height="28" viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg">
                <rect width="32" height="32" rx="8" fill="white"/>
                <path d="M10 20V12C10 10.8954 10.8954 10 12 10H14C15.1046 10 16 10.8954 16 12V20C16 21.1046 15.1046 22 14 22H12C10.8954 22 10 21.1046 10 20Z" fill="black"/>
                <path d="M18 16V12C18 10.8954 18.8954 10 20 10H20C21.1046 10 22 10.8954 22 12V16C22 17.1046 21.1046 18 20 18H20C18.8954 18 18 17.1046 18 16Z" fill="black"/>
                <circle cx="20" cy="21" r="3" fill="black"/>
            </svg>
        </div>
        PyMusic
    </div>
    <nav>
        <button class="nav-btn" onclick="loadView('home')">Home</button>
        <button class="nav-btn" onclick="loadView('search')">Search</button>
        <button class="nav-btn" onclick="loadView('library')">Library</button>
        <button id="auth-btn" class="btn-primary" onclick="handleAuth()">Login</button>
    </nav>
</header>

<main id="main-content">
    <!-- HOME VIEW -->
    <div id="view-home">
        <h2 class="section-title">Good Evening</h2>
        <div class="quick-links">
            <div class="quick-card" onclick="loadView('library')">
                <span class="quick-icon">📂</span>
                <span>Downloads</span>
            </div>
            <div class="quick-card" onclick="checkAuthAndLoad('liked')">
                <span class="quick-icon">♡</span>
                <span>Liked Songs</span>
            </div>
            <div class="quick-card" onclick="checkAuthAndLoad('playlists')">
                <span class="quick-icon">☰</span>
                <span>Playlists</span>
            </div>
            <div class="quick-card" onclick="loadView('search')">
                <span class="quick-icon">◎</span>
                <span>Discover</span>
            </div>
        </div>

        <h3 class="section-title">Your Top Artists</h3>
        <div id="top-artists-grid" class="card-grid" style="margin-bottom: 2rem;"></div>

        <h3 class="section-title">Most Played</h3>
        <div id="most-played-grid" class="card-grid"></div>
    </div>

    <!-- SEARCH VIEW -->
    <div id="view-search" class="hidden">
        <div class="search-container">
            <input type="text" id="search-input" placeholder="Search songs, artists, or albums..." onkeypress="if(event.key==='Enter') doSearch()">
            <button class="btn-primary" onclick="doSearch()">Search</button>
        </div>
        <h3 class="section-title" id="genre-header">Browse All</h3>
        <div class="genre-grid" id="genre-list"></div>
        <h3 class="section-title" id="trending-header" style="margin-top: 2rem;">Trending Now</h3>
        <div id="trending-tracks" class="list-group"></div>
        <div id="search-results"></div>
    </div>

    <!-- DETAIL VIEW (Album, Playlist, Artist) -->
    <div id="view-detail" class="hidden">
        
        <div id="detail-view-wrapper">
            <div id="detail-bg-layer"></div>
            <!-- Floating Back Button on top of wrapper -->
            <button class="detail-back-btn" onclick="closeDetailView()">← Back</button>
            <div id="detail-header"></div>
        </div>

        <div id="artist-tabs" class="tabs hidden">
            <div id="tab-tracks" class="tab active" onclick="switchArtistTab('tracks')">Popular</div>
            <div id="tab-albums" class="tab" onclick="switchArtistTab('albums')">Albums</div>
        </div>
        <h3 class="section-title" id="detail-title">Tracks</h3>
        <button id="download-all-btn" class="btn-primary hidden" onclick="downloadAll()" style="margin-bottom: 1rem;">Download All</button>
        <div id="detail-tracks" class="list-group"></div>
        <div id="detail-albums" class="card-grid hidden"></div>
    </div>

    <!-- LIBRARY VIEW -->
    <div id="view-library" class="hidden">
        <h2 class="section-title">Your Downloads</h2>
        <div id="library-list" class="list-group"></div>
    </div>
</main>

<!-- FULLSCREEN PLAYER -->
<div id="fullscreen-player">
    <!-- SECTION 1: MUSIC CONTROLS -->
    <div class="fs-snap-section fs-music-section">
        <div class="fs-header">
            <span style="font-size:0.8rem; color:white; opacity:0.7; text-transform:uppercase; letter-spacing:1px; font-weight:600;">Now Playing</span>
            
            <div class="fs-header-right">
                <!-- Volume Control (Desktop Only) -->
                <div class="fs-volume-control">
                    <span style="font-size: 0.85rem; color: var(--text-sub);">Volume</span>
                    <div class="volume-container" style="position: relative;">
                        <button class="control-btn" onclick="event.stopPropagation(); toggleVolumeDropdown()" title="Volume">🔊</button>
                        <div id="fs-volume-dropdown" class="volume-dropdown" style="position: absolute; bottom: 100%; right: 0; margin-bottom: 10px;">
                            <input type="range" orient="vertical" min="0" max="1" step="0.01" value="0.8" oninput="setVolume(this.value)">
                        </div>
                    </div>
                </div>
                
                <!-- Download Button (Mobile Only - Top Right) -->
                <button id="fs-download-btn-mobile" class="fs-download-btn-mobile" onclick="downloadCurrentTrack()">⬇</button>

                <!-- Close X Button (Top Right) -->
                <span class="close-fs" onclick="toggleFullscreenPlayer()">✕</span>
            </div>
        </div>
        
        <div class="fs-content-center" id="fs-swipe-container">
            <img id="fs-cover-img" class="fs-cover" src="" alt="Album Art">
            <div class="fs-info">
                <h2 id="fs-title-text" class="fs-title">Not Playing</h2>
                <p id="fs-artist-text" class="fs-artist">-</p>
            </div>
            
            <!-- PROGRESS BAR -->
            <div class="fs-progress-container">
                <span id="fs-current-time">0:00</span>
                <div style="flex:1; position: relative; height: 100%; display: flex; align-items: center;">
                    <div id="fs-progress-fill" class="progress-fill"></div>
                    <input type="range" id="fs-seek-slider" min="0" max="100" value="0" class="progress-slider">
                </div>
                <span id="fs-duration">0:00</span>
            </div>
            
            <!-- PLAYER BUTTONS -->
            <div class="fs-player-buttons">
                <button id="fs-shuffle-btn" class="fs-control-btn" onclick="toggleShuffle()" title="Shuffle">⇌</button>
                <button class="fs-control-btn" onclick="prevTrack()" title="Previous">⏮</button>
                <button class="fs-play-btn" onclick="togglePlay()">
                    <span id="fs-play-icon">▶</span>
                    <span id="fs-pause-icon" class="hidden">⏸</span>
                    <!-- Fullscreen Spinner -->
                    <div id="fs-play-spinner" class="play-spinner hidden"></div>
                </button>
                <button class="fs-control-btn" onclick="nextTrack()" title="Next">⏭</button>
                <button id="fs-repeat-btn" class="fs-control-btn" onclick="toggleRepeat()" title="Repeat">🔁</button>
            </div>
            
            <!-- DOWNLOAD BUTTON (DESKTOP ONLY) -->
            <button id="fs-download-btn-desktop" class="fs-download-btn-desktop" onclick="downloadCurrentTrack()">⬇ Download</button>
        </div>
        
        <div class="scroll-hint">
            <span>Swipe Up for Lyrics & Queue</span>
            <span>↑</span>
        </div>
    </div>

    <!-- SECTION 2: LYRICS & QUEUE (Scroll to access) -->
    <div class="fs-snap-section fs-details-section" id="fs-details-section">
        <div class="fs-grid-layout">
            <div class="fs-panel">
                <div class="panel-header">Lyrics</div>
                <div class="panel-content-scroll">
                    <div class="lyrics-content">Lyrics not available</div>
                </div>
            </div>
            <div class="fs-panel">
                <div class="panel-header">Up Next</div>
                <div class="panel-content-scroll">
                    <div id="fs-queue-list" class="queue-list"></div>
                </div>
            </div>
        </div>
    </div>
</div>

<!-- SIMILAR TRACK MODAL -->
<div id="similar-modal" class="modal-overlay" onclick="if(event.target === this) closeSimilarModal()">
    <div class="modal-content">
        <span class="close-modal" onclick="closeSimilarModal()">✕</span>
        <h2 class="section-title" style="margin-bottom: 1rem;">Similar Tracks</h2>
        <div id="similar-results" class="list-group"></div>
    </div>
</div>

<!-- FOOTER PLAYER -->
<footer>
    <div class="footer-padding" onclick="toggleFullscreenPlayer()">
        <div class="player-info">
            <img id="footer-cover" src="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='56' height='56'%3E%3Crect fill='%232a2a2a' width='56' height='56'/%3E%3C/svg%3E" alt="Cover" onclick="event.stopPropagation();">
            <div class="player-text">
                <span id="footer-title">Not Playing</span>
                <span id="footer-artist">-</span>
            </div>
        </div>

        <div class="player-center" onclick="event.stopPropagation();">
            <!-- PROGRESS BAR -->
            <div class="progress-container">
                <span id="current-time">0:00</span>
                <div style="flex:1; position: relative; height: 100%; display: flex; align-items: center;">
                    <div id="footer-progress-fill" class="progress-fill"></div>
                    <input type="range" id="seek-slider" min="0" max="100" value="0" class="progress-slider">
                </div>
                <span id="duration">0:00</span>
            </div>
            
            <div class="player-buttons">
                <button id="shuffle-btn" class="control-btn" onclick="event.stopPropagation(); toggleShuffle()" title="Shuffle">⇌</button>
                <button class="control-btn" onclick="event.stopPropagation(); prevTrack()" title="Previous">⏮</button>
                <button class="control-btn play-pause-btn" onclick="event.stopPropagation(); togglePlay()">
                    <span id="play-icon">▶</span>
                    <span id="pause-icon" class="hidden">⏸</span>
                    <!-- Footer Spinner -->
                    <div id="play-spinner" class="play-spinner hidden"></div>
                </button>
                <button class="control-btn" onclick="event.stopPropagation(); nextTrack()" title="Next">⏭</button>
                <button id="repeat-btn" class="control-btn" onclick="event.stopPropagation(); toggleRepeat()" title="Repeat">🔁</button>
            </div>
        </div>

<div class="player-right" onclick="event.stopPropagation();">
    <div class="volume-container">
        <button class="control-btn" onclick="event.stopPropagation(); toggleVolumeDropdown()" title="Volume">🔊</button>
        <div id="volume-dropdown" class="volume-dropdown">
            <input type="range" orient="vertical" min="0" max="1" step="0.01" value="0.8" oninput="setVolume(this.value)">
        </div>
    </div>
    <div class="status-msg" id="status-msg"></div>
    
    <!-- Mobile-only buttons (hidden on desktop) -->
    <button id="mobile-download-btn" onclick="event.stopPropagation(); downloadCurrentTrack()" title="Download" style="display: none;">⬇</button>
    <button id="mobile-play-btn" onclick="event.stopPropagation(); togglePlay()" title="Play/Pause" style="display: none;">
        <span id="mobile-play-icon">▶</span>
        <span id="mobile-pause-icon" class="hidden">⏸</span>
        <!-- Mobile Spinner -->
        <div id="mobile-play-spinner" class="play-spinner hidden"></div>
    </button>
</div>
        
        <audio id="audio-player"></audio>
    </div>
</footer>

<script>
    // --- STATE & CONFIG ---
    let currentTrackList = [];
    let currentTrackIndex = -1;
    let currentArtist = null;
    let token = null;
    let previousView = 'home';
    let currentParentCover = null;
    let currentPlayingTitle = "";
    let currentPlayingArtist = "";
    let currentPlayingCover = "";
    
    let currentPlayingId = null;
    let currentPlayingRealId = null; 
    let isPlaying = false;
    let currentPlayCounted = false;
    
    let repeatMode = 0; 
    let isShuffle = false;
    
    const STORAGE_KEY_HISTORY = 'pymusic_history';
    const STORAGE_KEY_STREAM_CACHE = 'pymusic_stream_cache';
    const MAX_HISTORY_ITEMS = 100;

    let libraryTracks = []; 

    // --- Swipe Logic (Horizontal for Song Change, Vertical for Scroll) ---
    let touchStartX = 0;
    let touchStartY = 0;
    let touchCurrentX = 0;
    let touchCurrentY = 0;
    let isDragging = false;
    const fsPlayer = document.getElementById('fullscreen-player');
    const fsContent = document.getElementById('fs-swipe-container');
    
    // Touch Start
    fsPlayer.addEventListener('touchstart', e => {
        if(e.target.closest('input') || e.target.closest('button')) return;
        touchStartX = e.touches[0].clientX;
        touchStartY = e.touches[0].clientY;
        isDragging = true;
        fsContent.style.transition = 'none';
    }, { passive: true });

    // Touch Move
    fsPlayer.addEventListener('touchmove', e => {
        if (!isDragging) return;
        
        touchCurrentX = e.touches[0].clientX;
        touchCurrentY = e.touches[0].clientY;
        
        const diffX = touchCurrentX - touchStartX;
        const diffY = touchCurrentY - touchStartY;
        
        // Determine if swipe is horizontal or vertical
        if (Math.abs(diffX) > Math.abs(diffY)) {
            // Horizontal Swipe - Change Song
            e.preventDefault(); // Stop vertical scroll
            fsContent.style.transform = `translateX(${diffX}px) rotate(${diffX * 0.02}deg)`;
        }
        // Else: Vertical Swipe - Allow natural scroll (handled by CSS scroll-snap)
    }, { passive: false });

    // Touch End
    fsPlayer.addEventListener('touchend', e => {
        if (!isDragging) return;
        isDragging = false;
        
        const diffX = touchCurrentX - touchStartX;
        const diffY = touchCurrentY - touchStartY;
        const threshold = 100;

        // Check if intention was a Horizontal Swipe (Song Change)
        if (Math.abs(diffX) > Math.abs(diffY) && Math.abs(diffX) > threshold) {
            const direction = diffX > 0 ? 1 : -1;

            const slideOutX = direction > 0 ? window.innerWidth : -window.innerWidth;
            fsContent.style.transition = 'transform 0.3s ease-out';
            fsContent.style.transform = `translateX(${slideOutX}px) rotate(${direction * 10}deg)`;

            setTimeout(() => {
                if (direction > 0) {
                    nextTrack();
                } else {
                    prevTrack();
                }

                const slideInX = direction > 0 ? -window.innerWidth : window.innerWidth;
                fsContent.style.transition = 'none';
                fsContent.style.transform = `translateX(${slideInX}px) rotate(0deg)`;

                void fsContent.offsetWidth;

                fsContent.style.transition = 'transform 0.3s cubic-bezier(0.2, 0.8, 0.2, 1)';
                fsContent.style.transform = `translateX(0)`;

            }, 300);
        } else {
            // Reset horizontal transform if not a song change swipe
            fsContent.style.transition = 'transform 0.3s ease-out';
            fsContent.style.transform = `translateX(0)`;
        }
    }, { passive: true });


    // --- Stream Cache Logic ---
    function getStreamUrl(id) {
        try {
            const cache = JSON.parse(localStorage.getItem(STORAGE_KEY_STREAM_CACHE) || '{}');
            return cache[id]; 
        } catch(e) { return null; }
    }

    function setStreamUrl(id, url) {
        try {
            const cache = JSON.parse(localStorage.getItem(STORAGE_KEY_STREAM_CACHE) || '{}');
            cache[id] = url;
            localStorage.setItem(STORAGE_KEY_STREAM_CACHE, JSON.stringify(cache));
        } catch(e) { console.error('Failed to save stream cache:', e); }
    }

    // --- Auth Handling ---
    async function checkAuth() {
        try {
            const res = await fetch('/api/auth/status');
            const data = await res.json();
            if (data.logged_in) {
                token = data.token;
                document.getElementById('auth-btn').textContent = 'Logout';
                document.getElementById('auth-btn').onclick = () => window.location.href = '/api/auth/logout';
                return true;
            }
        } catch(e) { console.error('Auth check failed:', e); }
        return false;
    }

    function handleAuth() {
        if(document.getElementById('auth-btn').textContent === 'Logout') {
            window.location.href = '/api/auth/logout';
        } else {
            window.location.href = '/api/auth/login';
        }
    }

    async function checkAuthAndLoad(view) {
        const isLoggedIn = await checkAuth();
        if(isLoggedIn) loadView(view);
        else showStatus("Please login first", true);
    }

    // --- API Proxy ---
    async function spotifyFetch(url) {
        if(!token) await checkAuth();
        try {
            const res = await fetch(`/api/spotify${url}`, {
                headers: { 'Authorization': `Bearer ${token}` }
            });
            if(res.status === 401) { showStatus("Session expired. Please login again.", true); return null; }
            if(res.status === 403) { showStatus("Permission denied. Check API Scopes.", true); return null; }
            if(res.status === 204) return {};
            if(!res.ok) { console.error(`Spotify API error: ${res.status}`); return null; }
            return res.json();
        } catch(e) { console.error('Spotify fetch error:', e); return null; }
    }

    // --- UI Logic ---
    function loadView(viewName) {
        ['view-home', 'view-search', 'view-detail', 'view-library'].forEach(id => {
            document.getElementById(id).classList.add('hidden');
        });
        
        if(viewName === 'home') {
            document.getElementById('view-home').classList.remove('hidden');
            loadHomeData();
        }
        if(viewName === 'search') {
            document.getElementById('view-search').classList.remove('hidden');
            if(document.getElementById('genre-list').children.length === 0) {
                loadGenres();
                loadTrending();
            } else {
                document.getElementById('genre-header').classList.remove('hidden');
                document.getElementById('genre-list').classList.remove('hidden');
                document.getElementById('trending-header').classList.remove('hidden');
                document.getElementById('trending-tracks').classList.remove('hidden');
                document.getElementById('search-results').innerHTML = '';
            }
        }
        if(viewName === 'library') {
            document.getElementById('view-library').classList.remove('hidden');
            loadLibrary();
        }
        if(viewName === 'liked') loadLikedSongs();
        if(viewName === 'playlists') loadPlaylists();
        
        if(viewName !== 'view-detail') {
            previousView = viewName;
        }
    }

    function closeDetailView() {
        loadView(previousView);
    }

    function showStatus(msg, isError = false) {
        const el = document.getElementById('status-msg');
        el.textContent = msg;
        el.style.color = isError ? 'var(--error)' : 'var(--success)';
        setTimeout(() => el.textContent = '', 10000);
    }

    // --- Volume Control ---
    function toggleVolumeDropdown() {
        const dd = document.getElementById('volume-dropdown');
        const fsDd = document.getElementById('fs-volume-dropdown');
        const isVisible = dd.classList.contains('show');
        
        dd.classList.toggle('show');
        if(fsDd) fsDd.classList.toggle('show');
    }
    function setVolume(val) { 
        document.getElementById('audio-player').volume = val; 
    }
    document.addEventListener('click', (e) => {
        const container = document.querySelector('.volume-container');
        if (container && !container.contains(e.target)) {
            document.getElementById('volume-dropdown').classList.remove('show');
            document.getElementById('fs-volume-dropdown').classList.remove('show');
        }
    });

    // --- Fullscreen Player ---
    function toggleFullscreenPlayer() {
        const fs = document.getElementById('fullscreen-player');
        if (fs.classList.contains('active')) {
            fs.classList.remove('active');
            fs.scrollTop = 0;
        } else {
            updateFullscreenContent();
            fs.classList.add('active');
        }
    }

    function updateFullscreenContent() {
        document.getElementById('fs-cover-img').src = currentPlayingCover || '';
        document.getElementById('fs-title-text').textContent = currentPlayingTitle || 'Not Playing';
        document.getElementById('fs-artist-text').textContent = currentPlayingArtist || '-';
        
        const playIcon = document.getElementById('fs-play-icon');
        const pauseIcon = document.getElementById('fs-pause-icon');
        if(isPlaying) { playIcon.classList.add('hidden'); pauseIcon.classList.remove('hidden'); }
        else { playIcon.classList.remove('hidden'); pauseIcon.classList.add('hidden'); }

        document.getElementById('fs-shuffle-btn').style.color = isShuffle ? 'var(--text)' : 'var(--text-sub)';
        document.getElementById('fs-repeat-btn').style.color = repeatMode !== 0 ? 'var(--text)' : 'var(--text-sub)';
        document.getElementById('fs-repeat-btn').textContent = repeatMode === 2 ? '🔂' : '🔁';

        renderQueue();
        updateProgress(true);
    }

    function renderQueue() {
        const queueContainer = document.getElementById('fs-queue-list');
        queueContainer.innerHTML = '';
        if (currentTrackList.length === 0) return;

        let upcoming = [];
        if (isShuffle) {
            let indices = Array.from({length: currentTrackList.length}, (_, i) => i);
            for (let i = indices.length - 1; i > 0; i--) {
                const j = Math.floor(Math.random() * (i + 1));
                [indices[i], indices[j]] = [indices[j], indices[i]];
            }
            const currentIdxInShuffled = indices.indexOf(currentTrackIndex);
            upcoming = indices.slice(currentIdxInShuffled + 1, currentIdxInShuffled + 11).map(idx => currentTrackList[idx]);
        } else {
            let start = currentTrackIndex + 1;
            if (start >= currentTrackList.length && repeatMode === 1) start = 0;
            if (start < currentTrackList.length) {
                for (let i = 0; i < 10; i++) {
                    let idx = start + i;
                    if (idx >= currentTrackList.length) {
                        if (repeatMode === 1) idx = idx % currentTrackList.length;
                        else break;
                    }
                    upcoming.push(currentTrackList[idx]);
                }
            }
        }

        if(upcoming.length === 0) {
            queueContainer.innerHTML = '<div style="color:var(--text-muted); font-size:0.9rem; text-align:center; padding:20px;">No upcoming tracks</div>';
        }

        upcoming.forEach(track => {
            const row = document.createElement('div');
            row.className = 'queue-item';
            let imgUrl = 'data:image/svg+xml,%3Csvg xmlns="http://www.w3.org/2000/svg" width="32" height="32"%3E%3Crect fill="%232a2a2a" width="32" height="32"/%3E%3C/svg%3E';
            if (track.album?.images?.[2]?.url) imgUrl = track.album.images[2].url;
            else if (track.path) imgUrl = `/api/cover?path=${encodeURIComponent(track.path)}`;
            else if (currentParentCover) imgUrl = currentParentCover;

            let name = track.name || track.title;
            let artist = track.artists ? track.artists[0].name : (track.artist || 'Unknown');
            let dur = track.duration_ms ? track.duration_ms/1000 : (track.duration || 0);

            row.innerHTML = `
                <img src="${imgUrl}" onerror="this.style.background='var(--surface-light)'">
                <div class="queue-info">
                    <div>${escapeHtml(name)}</div>
                    <span>${escapeHtml(artist)}</span>
                </div>
                <div class="queue-duration">${formatTime(dur)}</div>
            `;
            row.onclick = () => {
                const idx = currentTrackList.findIndex(t => t.id === track.id || t.path === track.path);
                if(idx !== -1) playTrackAtIndex(idx);
            };
            queueContainer.appendChild(row);
        });
    }

    function updatePlayPauseButton() {
        const playIcon = document.getElementById('play-icon');
        const pauseIcon = document.getElementById('pause-icon');
        const fsPlayIcon = document.getElementById('fs-play-icon');
        const fsPauseIcon = document.getElementById('fs-pause-icon');
        const mobilePlayIcon = document.getElementById('mobile-play-icon');
        const mobilePauseIcon = document.getElementById('mobile-pause-icon');
        
        if(isPlaying) {
            playIcon.classList.add('hidden');
            pauseIcon.classList.remove('hidden');
            fsPlayIcon.classList.add('hidden');
            fsPauseIcon.classList.remove('hidden');
            if(mobilePlayIcon) mobilePlayIcon.classList.add('hidden');
            if(mobilePauseIcon) mobilePauseIcon.classList.remove('hidden');
        } else {
            playIcon.classList.remove('hidden');
            pauseIcon.classList.add('hidden');
            fsPlayIcon.classList.remove('hidden');
            fsPauseIcon.classList.add('hidden');
            if(mobilePlayIcon) mobilePlayIcon.classList.remove('hidden');
            if(mobilePauseIcon) mobilePauseIcon.classList.add('hidden');
        }
        
        updateEqualizerState();
        if(document.getElementById('fullscreen-player').classList.contains('active')) updateFullscreenContent();
    }

    function setLoading(isLoading) {
        const spinners = [
            document.getElementById('play-spinner'),
            document.getElementById('fs-play-spinner'),
            document.getElementById('mobile-play-spinner')
        ];
        
        const icons = [
            'play-icon', 'pause-icon', 
            'fs-play-icon', 'fs-pause-icon', 
            'mobile-play-icon', 'mobile-pause-icon'
        ];

        if (isLoading) {
            spinners.forEach(s => { if(s) { s.classList.remove('hidden'); s.style.display = 'block'; } });
            icons.forEach(id => {
                const el = document.getElementById(id);
                if(el) el.classList.add('hidden');
            });
        } else {
            spinners.forEach(s => { if(s) { s.classList.add('hidden'); s.style.display = 'none'; } });
            updatePlayPauseButton();
        }
    }

    function updateEqualizerState() {
        document.querySelectorAll('.equalizer').forEach(eq => {
            eq.classList.add('hidden');
            eq.classList.add('paused');
        });
        const idsToHighlight = [currentPlayingId];
        if (currentPlayingRealId) idsToHighlight.push(currentPlayingRealId);

        idsToHighlight.forEach(id => {
            const eq = document.getElementById(`eq-${id}`);
            if(eq) {
                eq.classList.remove('hidden');
                if(isPlaying) eq.classList.remove('paused');
                else eq.classList.add('paused');
            }
        });
    }

    function togglePlay() {
        const audio = document.getElementById('audio-player');
        if(!audio.src || audio.src === window.location.href) {
            showStatus("No track selected", true);
            return;
        }
        if (audio.paused) audio.play();
        else audio.pause();
    }

    function toggleRepeat() {
        const btn = document.getElementById('repeat-btn');
        const fsBtn = document.getElementById('fs-repeat-btn');
        repeatMode = (repeatMode + 1) % 3; 
        if (repeatMode === 0) {
            btn.style.color = 'var(--text-sub)'; fsBtn.style.color = 'var(--text-sub)';
            btn.textContent = '🔁'; fsBtn.textContent = '🔁';
        } else if (repeatMode === 1) {
            btn.style.color = 'var(--text)'; fsBtn.style.color = 'var(--text)';
            btn.textContent = '🔁'; fsBtn.textContent = '🔁';
        } else {
            btn.style.color = 'var(--text)'; fsBtn.style.color = 'var(--text)';
            btn.textContent = '🔂'; fsBtn.textContent = '🔂';
            if (isShuffle) {
                isShuffle = false;
                document.getElementById('shuffle-btn').style.color = 'var(--text-sub)';
                document.getElementById('fs-shuffle-btn').style.color = 'var(--text-sub)';
                showStatus("Shuffle disabled (Repeat One is on)");
            }
        }
        showStatus(`Repeat: ${['Off', 'All', 'One'][repeatMode]}`);
    }

    function toggleShuffle() {
        const btn = document.getElementById('shuffle-btn');
        const fsBtn = document.getElementById('fs-shuffle-btn');
        isShuffle = !isShuffle;
        if (isShuffle) {
            btn.style.color = 'var(--text)'; fsBtn.style.color = 'var(--text)';
            if (repeatMode === 2) {
                repeatMode = 1; 
                document.getElementById('repeat-btn').textContent = '🔁';
                document.getElementById('fs-repeat-btn').textContent = '🔁';
                showStatus("Shuffle on (Repeat One disabled)");
            } else {
                showStatus("Shuffle on");
            }
        } else {
            btn.style.color = 'var(--text-sub)'; fsBtn.style.color = 'var(--text-sub)';
            showStatus("Shuffle off");
        }
    }

    function nextTrack() {
        if (currentTrackList.length === 0) return;
        let nextIndex;
        if (isShuffle) {
            do { nextIndex = Math.floor(Math.random() * currentTrackList.length); } while (nextIndex === currentTrackIndex && currentTrackList.length > 1);
        } else {
            nextIndex = currentTrackIndex + 1;
            if (nextIndex >= currentTrackList.length) {
                if (repeatMode === 1) nextIndex = 0;
                else { isPlaying = false; updatePlayPauseButton(); return; }
            }
        }
        playTrackAtIndex(nextIndex);
    }

    function prevTrack() {
        if (currentTrackList.length === 0) return;
        const audio = document.getElementById('audio-player');
        if (audio.currentTime > 3) { audio.currentTime = 0; return; }

        let prevIndex;
        if (isShuffle) {
             do { prevIndex = Math.floor(Math.random() * currentTrackList.length); } while (prevIndex === currentTrackIndex && currentTrackList.length > 1);
        } else {
            prevIndex = currentTrackIndex - 1;
            if (prevIndex < 0) {
                if (repeatMode === 1) prevIndex = currentTrackList.length - 1;
                else prevIndex = 0; 
            }
        }
        playTrackAtIndex(prevIndex);
    }

    function playTrackAtIndex(index) {
        if (index < 0 || index >= currentTrackList.length) return;
        const track = currentTrackList[index];
        if (track.path) {
            playLocal(track.path, track.title, track.artist, track.path);
            currentTrackIndex = index;
        } else if (track.id) {
            currentPlayingRealId = track.id; 
            if (track.preview_url) {
                playPreview(track.preview_url, track.id, track.name, track.artists[0].name, track.album?.images?.[0]?.url || currentParentCover, track.id);
            } else {
                ytFallbackPreview(track.name, track.artists[0].name, track.id);
            }
            currentTrackIndex = index;
        }
    }

    function formatTime(seconds) {
        if(isNaN(seconds) || seconds === Infinity) return "0:00";
        const m = Math.floor(seconds / 60);
        const s = Math.floor(seconds % 60);
        return `${m}:${s < 10 ? '0' : ''}${s}`;
    }

    function updateProgress(force = false) {
        const audio = document.getElementById('audio-player');
        const percent = (audio.currentTime / (audio.duration || 1)) * 100;
        
        const footerFill = document.getElementById('footer-progress-fill');
        const fsFill = document.getElementById('fs-progress-fill');
        if(footerFill) footerFill.style.width = `${percent}%`;
        if(fsFill) fsFill.style.width = `${percent}%`;

        document.getElementById('seek-slider').value = percent;
        document.getElementById('fs-seek-slider').value = percent;
        
        const currTime = formatTime(audio.currentTime);
        document.getElementById('current-time').textContent = currTime;
        document.getElementById('fs-current-time').textContent = currTime;
        
        const durTime = formatTime(audio.duration);
        document.getElementById('duration').textContent = durTime;
        document.getElementById('fs-duration').textContent = durTime;

        if (!currentPlayCounted && audio.currentTime >= 30) recordPlay();
    }

    function seekAudio() {
        const audio = document.getElementById('audio-player');
        const slider = document.getElementById('seek-slider');
        const time = (slider.value / 100) * (audio.duration || 0);
        audio.currentTime = time;
    }

    document.getElementById('fs-seek-slider').addEventListener('input', () => {
        const audio = document.getElementById('audio-player');
        const slider = document.getElementById('fs-seek-slider');
        const time = (slider.value / 100) * (audio.duration || 0);
        audio.currentTime = time;
    });

    // --- History & Most Played Logic ---
    function getHistory() {
        try { const data = localStorage.getItem(STORAGE_KEY_HISTORY); return data ? JSON.parse(data) : []; } 
        catch(e) { return []; }
    }
    function saveHistory(history) {
        try { localStorage.setItem(STORAGE_KEY_HISTORY, JSON.stringify(history)); } catch(e) {}
    }

    function recordPlay() {
        currentPlayCounted = true;
        if (!currentPlayingRealId && !currentPlayingId) return;
        
        const trackId = currentPlayingRealId || currentPlayingId;
        
        let history = getHistory();
        const existing = history.find(t => t.id === trackId);
        
        if (existing) {
            existing.count = (existing.count || 1) + 1;
            existing.timestamp = Date.now(); 
        } else {
            const trackObj = { id: trackId, count: 1, title: currentPlayingTitle, artist: currentPlayingArtist, cover: currentPlayingCover, timestamp: Date.now() };
            history.unshift(trackObj);
        }
        
        if (history.length > MAX_HISTORY_ITEMS) history = history.slice(0, MAX_HISTORY_ITEMS);
        saveHistory(history);
        
        if(!document.getElementById('view-home').classList.contains('hidden')) renderMostPlayedSection();
    }

    function renderMostPlayedSection() {
        const container = document.getElementById('most-played-grid');
        const history = getHistory();
        if(history.length < 3) { container.innerHTML = '<div style="color:var(--text-sub); font-size:0.85rem;">Play tracks for 30s to populate.</div>'; return; }

        const uniqueHistory = [];
        const seenIds = new Set();
        for (let item of history) {
            if (!seenIds.has(item.id)) {
                seenIds.add(item.id);
                uniqueHistory.push(item);
            }
        }

        uniqueHistory.sort((a, b) => b.count - a.count);

        const topTracks = uniqueHistory.slice(0, 6);
        container.innerHTML = '';
        topTracks.forEach(track => {
            const card = document.createElement('div');
            card.className = 'card';
            const imgUrl = track.cover || 'data:image/svg+xml,%3Csvg xmlns="http://www.w3.org/2000/svg" width="150" height="150"%3E%3Crect fill="%232a2a2a" width="150" height="150"/%3E%3C/svg%3E';
            
            const countText = track.count > 1 ? `${track.count} plays` : "1 play";

            card.innerHTML = `
                <img src="${imgUrl}" alt="${escapeHtml(track.title)}">
                <div class="play-count">${countText}</div>
                <div class="card-title">${escapeHtml(track.title)}</div>
                <div class="card-sub">${escapeHtml(track.artist)}</div>
            `;
            
            card.onclick = () => {
                if (libraryTracks.length === 0) {
                    document.getElementById('search-input').value = `${track.artist} ${track.title}`;
                    doSearch();
                    return;
                }

                const found = libraryTracks.find(t => 
                    t.title.toLowerCase() === track.title.toLowerCase() && 
                    t.artist.toLowerCase() === track.artist.toLowerCase()
                );
                if (found) {
                    playLocal(found.path, found.title, found.artist, found.path);
                    return;
                }

                const cachedUrl = getStreamUrl(track.id);
                if (cachedUrl) {
                    playPreview(cachedUrl, track.id, track.title, track.artist, track.cover, track.id);
                    return;
                }

                document.getElementById('search-input').value = `${track.artist} ${track.title}`;
                doSearch();
            };
            container.appendChild(card);
        });
    }

    function updatePlayingState(trackId, title, artist, coverUrl) {
        document.querySelectorAll('.list-item.playing').forEach(row => row.classList.remove('playing'));
        document.querySelectorAll('.equalizer').forEach(eq => { eq.classList.add('hidden'); eq.classList.add('paused'); });

        const idsToHighlight = [trackId];
        if (currentPlayingRealId && !idsToHighlight.includes(currentPlayingRealId)) idsToHighlight.push(currentPlayingRealId);

        idsToHighlight.forEach(id => {
            const row = document.getElementById(`track-row-${id}`);
            const ytRow = document.getElementById(`yt-row-${id}`);
            if (!ytRow && id.startsWith('yt-')) {
                const cleanId = id.replace('yt-', '');
                const cleanYtRow = document.getElementById(`yt-row-${cleanId}`);
                if (cleanYtRow) cleanYtRow.classList.add('playing');
            } else if (ytRow) { ytRow.classList.add('playing'); }
            if (row) row.classList.add('playing');
            
            const eq = document.getElementById(`eq-${id}`);
            if(eq) { eq.classList.remove('hidden'); if(isPlaying) eq.classList.remove('paused'); else eq.classList.add('paused'); }
        });
        
        currentPlayingId = trackId; 
        currentPlayingTitle = title;
        currentPlayingArtist = artist;
        currentPlayingCover = coverUrl;

        document.getElementById('footer-title').textContent = title;
        document.getElementById('footer-artist').textContent = artist;
        document.getElementById('footer-cover').src = coverUrl || 'data:image/svg+xml,%3Csvg xmlns="http://www.w3.org/2000/svg" width="56" height="56"%3E%3Crect fill="%232a2a2a" width="56" height="56"/%3E%3C/svg%3E';
        
        if(document.getElementById('fullscreen-player').classList.contains('active')) updateFullscreenContent();

        const index = currentTrackList.findIndex(t => 
            t.id === currentPlayingRealId || 
            t.path === currentPlayingId || 
            (trackId.startsWith('yt-') && t.id === trackId.replace('yt-', ''))
        );
        if (index !== -1) currentTrackIndex = index;
    }

    async function loadHomeData() {
        const container = document.getElementById('top-artists-grid');
        const data = await spotifyFetch('/me/top/artists?limit=10');
        
        if(data && data.items) {
            container.innerHTML = '';
            data.items.forEach(artist => {
                const card = document.createElement('div');
                card.className = 'card';
                card.innerHTML = `<img src="${artist.images?.[0]?.url || ''}" alt="${artist.name}" style="filter: grayscale(20%);"><div class="card-title">${artist.name}</div>`;
                card.onclick = () => openItem(artist, 'artist');
                container.appendChild(card);
            });
        } else {
            container.innerHTML = '<div style="padding:20px; text-align:center; color: var(--text-sub);">Log in to see your top artists</div>';
        }

        renderMostPlayedSection();
    }

    async function loadTrending() {
        const container = document.getElementById('trending-tracks');
        container.innerHTML = '<div class="spinner"></div>';
        
        const playlistId = "6UeSakyzhiEt4NB3UAd6NQ"; 
        try {
            const res = await fetch(`/api/spotify/playlists/${playlistId}/tracks?limit=50`, {
                headers: { 'Authorization': `Bearer ${token}` }
            });
            if(res.ok) {
                const data = await res.json();
                container.innerHTML = '';
                currentTrackList = []; 
                if(data && data.items) {
                    data.items.forEach(item => {
                        const track = item.track;
                        if(!track || !track.id) return;
                        currentTrackList.push(track);
                        renderTrackRow(track, container);
                    });
                    restorePlayerState();
                }
            } else {
                container.innerHTML = `<div style="padding:10px; color:var(--error)">Could not load trending tracks.</div>`;
            }
        } catch(e) { 
            console.error('Trending playlist error:', e);
            container.innerHTML = `<div style="padding:10px; color:var(--error)">Error loading tracks.</div>`;
        }
    }

    function handleListClick(track) {
        const idx = currentTrackList.findIndex(t => t.id === track.id);
        if (idx !== -1) currentTrackIndex = idx;
        currentPlayingRealId = track.id;
        if(track.preview_url) {
            playPreview(track.preview_url, track.id, track.name, track.artists[0].name, track.album?.images?.[0]?.url || currentParentCover, track.id);
        } else {
            ytFallbackPreview(track.name, track.artists[0].name, track.id);
        }
    }

    function renderTrackRow(track, container, fallbackCover=null) {
        const row = document.createElement('div');
        row.className = 'list-item';
        row.id = `track-row-${track.id}`; 
        
        const trackName = escapeHtml(track.name);
        const artistName = escapeHtml(track.artists[0].name);
        const coverUrl = track.album?.images?.[2]?.url || fallbackCover || 'data:image/svg+xml,%3Csvg xmlns="http://www.w3.org/2000/svg" width="44" height="44"%3E%3Crect fill="%232a2a2a" width="44" height="44"/%3E%3C/svg%3E';
        const duration = track.duration_ms ? formatTime(track.duration_ms / 1000) : '';
        
        row.innerHTML = `
            <img src="${coverUrl}" alt="${trackName}">
            <div class="list-info" onclick='handleListClick(${JSON.stringify(track).replace(/'/g, "&#39;")})'>
                <div class="equalizer hidden" id="eq-${track.id}">
                    <div class="bar"></div>
                    <div class="bar"></div>
                    <div class="bar"></div>
                </div>
                <div>
                    <div style="font-weight:500">${trackName}</div>
                    <div class="card-sub">${track.artists.map(a=>escapeHtml(a.name)).join(', ')}</div>
                </div>
            </div>
            <div class="list-meta">${duration}</div>
            <div class="list-actions">
                <button class="action-btn dl-btn" id="dl-${track.id}" onclick='event.stopPropagation(); downloadTrack("${track.id}", "${trackName}", "${artistName}", "${track.album?.images?.[0]?.url || fallbackCover || ""}")'>Download</button>
                <button class="action-btn similar-btn" onclick='event.stopPropagation(); openSimilarModal("${trackName}", "${artistName}")'>Similar</button>
            </div>
        `;
        container.appendChild(row);
    }

    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    async function loadGenres() {
        const data = await spotifyFetch('/browse/categories?limit=20');
        const container = document.getElementById('genre-list');
        container.innerHTML = '';
        if(data && data.categories) {
            data.categories.items.forEach(cat => {
                const card = document.createElement('div');
                card.className = 'genre-card';
                const bgUrl = cat.icons && cat.icons.length > 0 ? cat.icons[0].url : '';
                
                card.innerHTML = `
                    <div class="genre-bg" style="background-image: url('${bgUrl}');"></div>
                    <div class="genre-overlay">
                        <div class="genre-name">${cat.name}</div>
                    </div>
                `;
                card.onclick = () => openCategory(cat);
                container.appendChild(card);
            });
        }
    }

    async function openCategory(cat) {
        document.getElementById('genre-header').classList.add('hidden');
        document.getElementById('genre-list').classList.add('hidden');
        document.getElementById('trending-header').classList.add('hidden');
        document.getElementById('trending-tracks').classList.add('hidden');

        const container = document.getElementById('search-results');
        container.innerHTML = `<h3 class="section-title">Playlists matching "${escapeHtml(cat.name)}"</h3><div class="spinner"></div>`;

        try {
            const query = encodeURIComponent(cat.name);
            const data = await spotifyFetch(`/search?q=${query}&type=playlist&limit=20`);
            
            if(data && data.playlists && data.playlists.items.length > 0) {
                container.innerHTML = '';
                
                const h = document.createElement('h3');
                h.className = 'section-title';
                h.style.marginTop = '1.5rem';
                h.textContent = `Playlists matching "${escapeHtml(cat.name)}"`;
                container.appendChild(h);

                const grid = document.createElement('div');
                grid.className = 'card-grid';

                const lowerQuery = cat.name.toLowerCase();
                const relevantPlaylists = data.playlists.items.filter(p => 
                    p && p.name && p.name.toLowerCase().includes(lowerQuery) && p.tracks.total > 0
                );

                if(relevantPlaylists.length === 0) {
                     container.innerHTML = '<div style="padding:20px; color:var(--text-sub)">No playlists found for this genre.</div>';
                     return;
                }

                relevantPlaylists.forEach(p => {
                    const card = document.createElement('div');
                    card.className = 'card';
                    const imgUrl = p.images?.[0]?.url || 'data:image/svg+xml,%3Csvg xmlns="http://www.w3.org/2000/svg" width="150" height="150"%3E%3Crect fill="%232a2a2a" width="150" height="150"/%3E%3C/svg%3E';
                    card.innerHTML = `
                        <img src="${imgUrl}" alt="${escapeHtml(p.name)}">
                        <div class="card-title">${escapeHtml(p.name)}</div>
                        <div class="card-sub">${escapeHtml(p.description || '')}</div>
                    `;
                    card.onclick = () => openItem(p, 'playlist');
                    grid.appendChild(card);
                });
                
                container.appendChild(grid);
            } else {
                container.innerHTML = '<div style="padding:20px; color:var(--text-sub)">No playlists found for this genre.</div>';
            }
        } catch(e) {
            console.error('Category search error:', e);
            container.innerHTML = '<div style="padding:20px; color:var(--error)">Error loading genre.</div>';
        }
    }

    async function doSearch() {
        const rawQuery = document.getElementById('search-input').value.trim();
        if(!rawQuery) return;

        document.getElementById('genre-header').classList.add('hidden');
        document.getElementById('genre-list').classList.add('hidden');
        document.getElementById('trending-header').classList.add('hidden');
        document.getElementById('trending-tracks').classList.add('hidden');

        const container = document.getElementById('search-results');
        container.innerHTML = '<div class="spinner"></div>';

        const query = encodeURIComponent(rawQuery);
        const data = await spotifyFetch(`/search?q=${query}&type=track,album,artist,playlist&limit=10`);
        container.innerHTML = '';

        if(!data) {
            container.innerHTML = '<div style="padding:20px; color:var(--error)">Search failed</div>';
            return;
        }

        currentTrackList = [];
        
        function makeSection(title, items, type) {
            if(!items || items.length === 0) return;
            const h = document.createElement('h3');
            h.className = 'section-title';
            h.style.marginTop = '1.5rem';
            h.textContent = title;
            container.appendChild(h);

            if(type === 'track') {
                const list = document.createElement('div');
                list.className = 'list-group';
                items.forEach(track => {
                    currentTrackList.push(track);
                    renderTrackRow(track, list);
                });
                container.appendChild(list);
            } else {
                const grid = document.createElement('div');
                grid.className = 'card-grid';
                items.forEach(item => {
                    const card = document.createElement('div');
                    card.className = 'card';
                    let imgUrl = item.images?.[0]?.url || 'data:image/svg+xml,%3Csvg xmlns="http://www.w3.org/2000/svg" width="150" height="150"%3E%3Crect fill="%232a2a2a" width="150" height="150"/%3E%3C/svg%3E';
                    let subtitle = '';
                    if(type === 'artist') subtitle = 'Artist';
                    if(type === 'album') subtitle = item.artists?.[0]?.name || 'Album';
                    if(type === 'playlist') subtitle = item.owner?.display_name || 'Playlist';
                    
                    card.innerHTML = `<img src="${imgUrl}" alt="${escapeHtml(item.name)}" style="${type === 'artist' ? 'border-radius:50%;' : ''}"><div class="card-title">${escapeHtml(item.name)}</div><div class="card-sub">${escapeHtml(subtitle)}</div>`;
                    card.onclick = () => openItem(item, type);
                    grid.appendChild(card);
                });
                container.appendChild(grid);
            }
        }

        if(data.tracks) makeSection('Tracks', data.tracks.items, 'track');
        if(data.artists) makeSection('Artists', data.artists.items, 'artist');
        if(data.albums) makeSection('Albums', data.albums.items, 'album');

        if(data.playlists) {
            const lowerQuery = rawQuery.toLowerCase();
            const relevantPlaylists = data.playlists.items.filter(p => 
                p && p.name && p.name.toLowerCase().includes(lowerQuery) && p.tracks.total > 0
            );
            if(relevantPlaylists.length > 0) {
                makeSection('Public Playlists', relevantPlaylists, 'playlist');
            }
        }

        restorePlayerState();
    }

async function openItem(item, type) {
    if(type === 'track') {
        const idx = currentTrackList.findIndex(t => t.id === item.id);
        if (idx !== -1) currentTrackIndex = idx;
        currentPlayingRealId = item.id;
        if(item.preview_url) {
            playPreview(item.preview_url, item.id, item.name, item.artists[0].name, item.album?.images?.[0]?.url, item.id);
        } else {
            ytFallbackPreview(item.name, item.artists[0].name, item.id);
        }
        return;
    }
    
    ['view-search', 'view-home', 'view-library'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.classList.add('hidden');
    });
    
    const detailView = document.getElementById('view-detail');
    if (!detailView) {
        console.error('view-detail element not found!');
        return;
    }
    detailView.classList.remove('hidden');
    
    const header = document.getElementById('detail-header');
    const bgLayer = document.getElementById('detail-bg-layer');
    const titleEl = document.getElementById('detail-title');
    const tracksDiv = document.getElementById('detail-tracks');
    const albumsDiv = document.getElementById('detail-albums');
    const artistTabs = document.getElementById('artist-tabs');
    
    if (!header || !bgLayer || !titleEl || !tracksDiv || !albumsDiv || !artistTabs) {
        console.error('Missing detail view elements!');
        return;
    }
    
    artistTabs.classList.add('hidden');
    albumsDiv.classList.add('hidden');
    tracksDiv.classList.remove('hidden');
    currentTrackList = [];
    currentParentCover = null;

    bgLayer.style.backgroundImage = 'none';

    if(type === 'playlist') {
        const data = await spotifyFetch(`/playlists/${item.id}`);
        if(!data) return;
        const pImg = item.images?.[0]?.url || data.images?.[0]?.url || '';
        bgLayer.style.backgroundImage = `url('${pImg}')`;

        header.innerHTML = `<img src="${pImg}" style="width:180px; height:180px; box-shadow: 0 8px 40px rgba(0,0,0,.5); border-radius: 8px;">
                            <div><h1 style="font-size:2.5rem; margin-bottom:0.5rem; font-weight:800;">${escapeHtml(item.name)}</h1>
                            <p class="text-sub">${escapeHtml(data.owner.display_name)} • ${data.tracks.total} songs</p></div>`;
        titleEl.textContent = "Tracks";
        const dlBtn = document.getElementById('download-all-btn');
        if (dlBtn) dlBtn.classList.remove('hidden');
        renderTracks(data.tracks.items, false, false, pImg);
    } else if (type === 'album') {
        const data = await spotifyFetch(`/albums/${item.id}`);
        if(!data) return;
        const aImg = item.images?.[0]?.url || '';
        bgLayer.style.backgroundImage = `url('${aImg}')`;

        header.innerHTML = `<img src="${aImg}" style="width:180px; height:180px; box-shadow: 0 8px 40px rgba(0,0,0,.5); border-radius: 8px;">
                            <div><h1 style="font-size:2.5rem; margin-bottom:0.5rem; font-weight:800;">${escapeHtml(item.name)}</h1>
                            <p class="text-sub">${escapeHtml(item.artists[0].name)} • ${item.total_tracks} songs</p></div>`;
        titleEl.textContent = "Tracks";
        const dlBtn = document.getElementById('download-all-btn');
        if (dlBtn) dlBtn.classList.remove('hidden');
        renderTracks(data.tracks.items, true, false, aImg);
    } else if (type === 'artist') {
        openArtist(item);
    }
}

async function openArtist(item) {
    ['view-search', 'view-home'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.classList.add('hidden');
    });
    
    const detailView = document.getElementById('view-detail');
    if (!detailView) {
        console.error('view-detail element not found!');
        return;
    }
    detailView.classList.remove('hidden');
    
    currentArtist = item;
    const header = document.getElementById('detail-header');
    const bgLayer = document.getElementById('detail-bg-layer');
    
    if (!header || !bgLayer) {
        console.error('Missing header or background layer!');
        return;
    }
    
    header.innerHTML = '<div class="spinner" style="margin: 0; display: inline-block;"></div> Loading Artist...';
    bgLayer.style.backgroundImage = 'none';
    
    const artistData = await spotifyFetch(`/artists/${item.id}`);
    
    if(!artistData) {
        header.innerHTML = '<div style="color:var(--error)">Error loading artist data</div>';
        return;
    }

    const artImg = artistData.images?.[0]?.url || '';
    bgLayer.style.backgroundImage = `url('${artImg}')`;

    header.innerHTML = `<img src="${artImg}" style="width:180px; height:180px; border-radius:50%; box-shadow: 0 8px 40px rgba(0,0,0,.5);">
                        <div><h1 style="font-size:3rem; margin-bottom:0.5rem; font-weight:800;">${escapeHtml(artistData.name)}</h1>
                        <p class="text-sub" style="font-size:1.1rem">Artist</p></div>`;
    
    const artistTabs = document.getElementById('artist-tabs');
    const dlBtn = document.getElementById('download-all-btn');
    
    if (artistTabs) artistTabs.classList.remove('hidden');
    if (dlBtn) dlBtn.classList.add('hidden');
    
    const tracksTab = document.getElementById('tab-tracks');
    const albumsTab = document.getElementById('tab-albums');
    
    if (tracksTab) tracksTab.classList.add('active');
    if (albumsTab) albumsTab.classList.remove('active');
    
    switchArtistTab('tracks');
}

    async function switchArtistTab(tab) {
        document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
        if(tab === 'tracks') document.getElementById('tab-tracks').classList.add('active');
        if(tab === 'albums') document.getElementById('tab-albums').classList.add('active');

        const tracksDiv = document.getElementById('detail-tracks');
        const albumsDiv = document.getElementById('detail-albums');
        
        if(tab === 'tracks') {
            tracksDiv.classList.remove('hidden');
            albumsDiv.classList.add('hidden');
            document.getElementById('detail-title').textContent = "Popular";
            tracksDiv.innerHTML = '<div class="spinner"></div>';
            
            const data = await spotifyFetch(`/artists/${currentArtist.id}/top-tracks?market=US`);
            if(data) renderTracks(data.tracks, false, false);
        } else {
            tracksDiv.classList.add('hidden');
            albumsDiv.classList.remove('hidden');
            document.getElementById('detail-title').textContent = "Discography";
            albumsDiv.innerHTML = '<div class="spinner"></div>';
            
            const data = await spotifyFetch(`/artists/${currentArtist.id}/albums?limit=20`);
            albumsDiv.innerHTML = '';
            if(data && data.items) {
                data.items.forEach(album => {
                    const card = document.createElement('div');
                    card.className = 'card';
                    const albImg = album.images?.[0]?.url || '';
                    card.innerHTML = `<img src="${albImg}" alt="${escapeHtml(album.name)}"><div class="card-title">${escapeHtml(album.name)}</div><div class="card-sub">${album.release_date.split('-')[0]}</div>`;
                    card.onclick = () => openItem(album, 'album');
                    albumsDiv.appendChild(card);
                });
            }
        }
    }

    function renderTracks(items, isSimple, append=false, fallbackCover=null) {
        const tracksDiv = document.getElementById('detail-tracks');
        
        if(!append) {
            tracksDiv.innerHTML = '';
            currentTrackList = [];
        }
        
        if(!items || items.length === 0) {
            tracksDiv.innerHTML = '<div style="padding:20px; text-align:center; color: var(--text-sub);">No tracks found</div>';
            return;
        }
        
        items.forEach(t => {
            const track = isSimple ? t : (t.track || t);
            if(!track || !track.id) return;
            currentTrackList.push(track);
            renderTrackRow(track, tracksDiv, fallbackCover);
        });

        restorePlayerState();
    }

    async function loadLikedSongs() {
        document.getElementById('view-detail').classList.remove('hidden');
        const header = document.getElementById('detail-header');
        const bgLayer = document.getElementById('detail-bg-layer');
        bgLayer.style.backgroundImage = 'linear-gradient(135deg, #450af5, #c4efd9)';
        
        header.innerHTML = `<div><h1 style="font-size:2.5rem; font-weight:800;">Liked Songs</h1></div>`;
        document.getElementById('detail-title').textContent = "Your Collection";
        document.getElementById('download-all-btn').classList.remove('hidden');
        document.getElementById('artist-tabs').classList.add('hidden');
        document.getElementById('detail-albums').classList.add('hidden');
        document.getElementById('detail-tracks').classList.remove('hidden');
        
        const tracksDiv = document.getElementById('detail-tracks');
        tracksDiv.innerHTML = '<div class="spinner"></div>';
        
        const data = await spotifyFetch('/me/tracks');
        
        if(data && data.items) {
            renderTracks(data.items, false, false);
        } else {
            tracksDiv.innerHTML = '<div style="padding:20px; color:var(--error)">Error loading songs. Check console or try logging out and back in.</div>';
        }
    }

function openSimilarModal(title, artist) {
    document.getElementById('similar-modal').style.display = 'flex';

    const container = document.getElementById('similar-results');
    container.innerHTML = '<div class="spinner"></div>';

    const query = `${artist} ${title} official audio`;

    fetch(`/api/search-yt?q=${encodeURIComponent(query)}`, { cache: "no-store" })
        .then(res => {
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            return res.json();
        })
        .then(data => {
            container.innerHTML = '';

            if (!data || !Array.isArray(data.results) || data.results.length === 0) {
                container.innerHTML =
                    '<div style="padding:20px;text-align:center;color:var(--text-sub)">No results found</div>';
                return;
            }

            data.results.forEach(vid => {
                const row = document.createElement('div');
                row.className = 'list-item';
                row.id = `yt-row-${vid.id}`;

                const duration = vid.duration ? formatTime(vid.duration) : '';

                const safeTitle = escapeHtml(vid.title || '');
                const safeUploader = escapeHtml(vid.uploader || '');
                const thumb = vid.thumbnail || '';

                row.innerHTML = `
                    <img src="${thumb}" style="width:60px;height:45px;border-radius:6px">
                    <div class="list-info">
                        <div class="equalizer hidden" id="eq-${vid.id}">
                            <div class="bar"></div>
                            <div class="bar"></div>
                            <div class="bar"></div>
                        </div>
                        <div>
                            <div style="font-weight:500">${safeTitle}</div>
                            <div class="card-sub">${safeUploader}</div>
                        </div>
                    </div>
                    <div class="list-meta">${duration}</div>
                    <div class="list-actions">
                        <button class="action-btn similar-btn">Play</button>
                        <button class="action-btn dl-btn">Download</button>
                    </div>
                `;

                row.querySelector('.list-info').onclick = () =>
                    playYTStream(vid.id, safeTitle, safeUploader, thumb);

                row.querySelector('.similar-btn').onclick = e => {
                    e.stopPropagation();
                    playYTStream(vid.id, safeTitle, safeUploader, thumb);
                };

                row.querySelector('.dl-btn').onclick = e => {
                    e.stopPropagation();
                    downloadYTTrack(vid.id, safeTitle, safeUploader);
                };

                container.appendChild(row);
            });

            restorePlayerState();
        })
        .catch(e => {
            console.error('YouTube search error:', e);
            container.innerHTML =
                '<div style="padding:20px;color:var(--error)">Error searching</div>';
        });
}

    function closeSimilarModal() {
        document.getElementById('similar-modal').style.display = 'none';
    }

    async function playYTStream(videoId, title, artist, thumbnail) {
        // Loading triggers immediately so user knows click registered
        setLoading(true); 
        showStatus("Getting stream URL...");
        
        try {
            const res = await fetch(`/api/yt-stream?id=${videoId}`);
            const data = await res.json();
            if(data.url) {
                playPreview(data.url, `yt-${videoId}`, title, artist, thumbnail, null);
                setStreamUrl(`yt-${videoId}`, data.url);
            } else {
                setLoading(false);
                showStatus("Failed to get stream", true);
            }
        } catch(e) {
            setLoading(false);
            showStatus("Stream error", true);
            console.error('YT stream error:', e);
        }
    }

    async function loadPlaylists() {
        document.getElementById('view-detail').classList.remove('hidden');
        document.getElementById('detail-header').innerHTML = '<div><h1 style="font-size:2.5rem; font-weight:800;">Your Playlists</h1></div>';
        document.getElementById('detail-bg-layer').style.backgroundImage = 'none';
        document.getElementById('detail-tracks').innerHTML = '';
        document.getElementById('detail-albums').classList.remove('hidden');
        document.getElementById('detail-title').textContent = "";
        document.getElementById('download-all-btn').classList.add('hidden');
        document.getElementById('artist-tabs').classList.add('hidden');
        
        const data = await spotifyFetch('/me/playlists?limit=20');
        const grid = document.getElementById('detail-albums');
        grid.innerHTML = '<div class="spinner"></div>';
        
        if(data && data.items) {
            grid.innerHTML = '';
            data.items.forEach(list => {
                const card = document.createElement('div');
                card.className = 'card';
                const plImg = list.images?.[0]?.url || '';
                card.innerHTML = `<img src="${plImg}" alt="${escapeHtml(list.name)}"><div class="card-title">${escapeHtml(list.name)}</div><div class="card-sub">${escapeHtml(list.owner.display_name)}</div>`;
                card.onclick = () => openItem(list, 'playlist');
                grid.appendChild(card);
            });
        }
    }

    async function ytFallbackPreview(title, artist, spotifyId) {
        const query = `${artist} ${title} official audio`;
        showStatus("Searching YouTube for preview...");
        try {
            const res = await fetch(`/api/search-yt?q=${encodeURIComponent(query)}`);
            const data = await res.json();
            if(data.results && data.results.length > 0) {
                playYTStream(data.results[0].id, title, artist, data.results[0].thumbnail, spotifyId);
            } else {
                showStatus("No preview found", true);
            }
        } catch(e) {
            showStatus("Preview search failed", true);
            console.error('YT fallback error:', e);
        }
    }

    async function downloadTrack(id, title, artist, imgUrl) {
        const btn = document.getElementById(`dl-${id}`);
        if(!btn) return;
        
        const originalText = btn.textContent;
        btn.textContent = "Queued";
        btn.classList.add('downloading');
        btn.disabled = true;
        
        showStatus(`Starting download: ${title}`);
        
        try {
            const res = await fetch('/api/download', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ id, title, artist, imgUrl })
            });
            
            const result = await res.json();
            
            if(result.success) {
                btn.textContent = "Done";
                btn.style.borderColor = "var(--success)";
                btn.style.color = "var(--success)";
                showStatus(`Downloaded: ${title}`);
            } else {
                btn.textContent = "Retry";
                btn.classList.remove('downloading');
                btn.disabled = false;
                showStatus(`Error: ${result.error}`, true);
            }
        } catch(e) {
            btn.textContent = originalText;
            btn.classList.remove('downloading');
            btn.disabled = false;
            showStatus("Download failed", true);
            console.error('Download error:', e);
        }
    }

    function downloadCurrentTrack() {
    if (!currentPlayingTitle || !currentPlayingArtist) {
        showStatus("No track playing", true);
        return;
    }
    
    const mobileBtn = document.getElementById('fs-download-btn-mobile');
    const desktopBtn = document.getElementById('fs-download-btn-desktop');
    
    if(mobileBtn) {
        mobileBtn.textContent = "⏳";
        mobileBtn.disabled = true;
    }
    if(desktopBtn) {
        desktopBtn.textContent = "Downloading...";
        desktopBtn.disabled = true;
    }
    
    downloadTrack(
        currentPlayingRealId || currentPlayingId, 
        currentPlayingTitle, 
        currentPlayingArtist, 
        currentPlayingCover
    ).then(() => {
        if(mobileBtn) {
            mobileBtn.textContent = "⬇";
            mobileBtn.disabled = false;
        }
        if(desktopBtn) {
            desktopBtn.textContent = "⬇ Download";
            desktopBtn.disabled = false;
        }
    });
}
    
    async function downloadYTTrack(videoId, title, artist) {
        showStatus(`Downloading YouTube audio...`);
        try {
            const res = await fetch('/api/download', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ 
                    title: title, artist: artist, youtube_id: videoId, imgUrl: null 
                })
            });
            const result = await res.json();
            if(result.success) {
                showStatus(`Downloaded: ${title}`);
                closeSimilarModal();
            } else {
                showStatus(`Download failed: ${result.error}`, true);
            }
        } catch(e) {
            showStatus("Download error", true);
            console.error('YT download error:', e);
        }
    }

    async function downloadAll() {
        const totalTracks = currentTrackList.length;
        let downloaded = 0;
        
        showStatus(`Starting batch download of ${totalTracks} tracks...`);
        
        for(const track of currentTrackList) {
            const btn = document.getElementById(`dl-${track.id}`);
            if(btn && btn.textContent !== "Done") {
                await downloadTrack(track.id, track.name, track.artists[0].name, track.album?.images?.[0]?.url);
                downloaded++;
                showStatus(`Downloaded ${downloaded}/${totalTracks} tracks`);
                await new Promise(r => setTimeout(r, 1000)); 
            }
        }
        showStatus(`Batch download complete: ${downloaded} tracks`);
    }

    function playPreview(url, id, title, artist, coverUrl, realId = null) {
        if(!url) {
            showStatus("No preview available", true);
            setLoading(false);
            return;
        }
        
        // Show spinner immediately to indicate click registered
        setLoading(true);

        if (realId) setStreamUrl(realId, url);

        if (!coverUrl) coverUrl = 'data:image/svg+xml,%3Csvg xmlns="http://www.w3.org/2000/svg" width="56" height="56"%3E%3Crect fill="%232a2a2a" width="56" height="56"/%3E%3C/svg%3E';
        
        const audio = document.getElementById('audio-player');
        audio.src = url;
        currentPlayCounted = false;

        if(realId) currentPlayingRealId = realId;
        else if (!id.startsWith('yt-')) currentPlayingRealId = id;
        else currentPlayingRealId = null;
        
        updatePlayingState(id, title, artist, coverUrl);
        
        document.getElementById('seek-slider').value = 0;
        document.getElementById('fs-seek-slider').value = 0;
        document.getElementById('current-time').textContent = "0:00";
        document.getElementById('fs-current-time').textContent = "0:00";
        
        const playPromise = audio.play();

        if (playPromise !== undefined) {
            playPromise.then(() => {
                isPlaying = true;
                updatePlayPauseButton();
            })
            .catch(error => {
                console.error("Playback prevented or failed:", error);
                isPlaying = false;
                setLoading(false);
                updatePlayPauseButton();
                if (error.name === 'NotAllowedError') showStatus("Autoplay blocked. Click Play.", true);
                else showStatus("Playback failed (Source error)", true);
            });
        }
    }

    async function loadLibrary() {
        try {
            const res = await fetch('/api/library');
            const files = await res.json();
            const div = document.getElementById('library-list');
            div.innerHTML = '';
            currentTrackList = [];
            libraryTracks = []; 
            
            if(files.length === 0) {
                div.innerHTML = '<div style="padding:20px; text-align:center; color: var(--text-sub);">No downloads yet</div>';
                return;
            }
            
            files.forEach(f => {
                libraryTracks.push(f);
                
                const row = document.createElement('div');
                row.className = 'list-item';
                const domId = `file-${f.path.replace(/[^a-zA-Z0-9]/g, '_')}`;
                row.id = `track-row-${domId}`; 
                
                currentTrackList.push(f);

                const coverUrl = `/api/cover?path=${encodeURIComponent(f.path)}`;
                const genericCover = 'data:image/svg+xml,%3Csvg xmlns="http://www.w3.org/2000/svg" width="44" height="44"%3E%3Crect fill="%232a2a2a" width="44" height="44"/%3E%3C/svg%3E';
                const duration = f.duration ? formatTime(f.duration) : '';

                row.innerHTML = `
                    <img src="${coverUrl}" onerror="this.src='${genericCover}'" style="width:44px; height:44px; margin-right:0.75rem; border-radius:6px; object-fit:cover;">
                    <div class="list-info" onclick='playLocal("${f.path}", "${escapeHtml(f.title)}", "${escapeHtml(f.artist)}", "${domId}")'>
                        <div class="equalizer hidden" id="eq-${domId}">
                            <div class="bar"></div>
                            <div class="bar"></div>
                            <div class="bar"></div>
                        </div>
                        <div>
                            <div style="font-weight:500">${escapeHtml(f.title)}</div>
                            <div class="card-sub">${escapeHtml(f.artist)}</div>
                        </div>
                    </div>
                    <div class="list-meta">${duration}</div>
                    <div class="list-actions">
                         <button class="action-btn" onclick='event.stopPropagation(); playLocal("${f.path}", "${escapeHtml(f.title)}", "${escapeHtml(f.artist)}", "${domId}")'>Play</button>
                    </div>
                `;
                div.appendChild(row);
            });
            restorePlayerState();
        } catch(e) {
            console.error('Library load error:', e);
            showStatus("Failed to load library", true);
        }
    }

    function playLocal(path, title, artist, id) {
        const coverUrl = `/api/cover?path=${encodeURIComponent(path)}`;
        const audio = document.getElementById('audio-player');
        audio.src = `/api/files?path=${encodeURIComponent(path)}`;
        
        currentPlayCounted = false;
        currentPlayingRealId = null;
        
        setLoading(true); // Show loading on click

        updatePlayingState(id, title, artist, coverUrl);
        
        audio.play().then(() => {
            isPlaying = true;
            updatePlayPauseButton();
        }).catch(e => {
            setLoading(false);
            console.error("Local play error:", e);
        });
    }

    function restorePlayerState() {
        if(currentPlayingId) {
            updatePlayingState(currentPlayingId, currentPlayingTitle, currentPlayingArtist, currentPlayingCover);
        }
    }

    // --- Audio Event Listeners ---
    const audio = document.getElementById('audio-player');
    
    audio.onplay = () => { 
        isPlaying = true; 
        updatePlayPauseButton(); 
    };
    
    audio.onpause = () => { 
        isPlaying = false; 
        setLoading(false);
        updatePlayPauseButton(); 
    };
    
    audio.ontimeupdate = updateProgress;
    
    document.getElementById('seek-slider').addEventListener('input', seekAudio);
    
    audio.onended = () => {
        if(repeatMode === 2) { audio.currentTime = 0; audio.play(); } else { nextTrack(); }
    };

    // Fires when audio resumes playing after buffering
    audio.onplaying = () => {
        setLoading(false);
    };

    // Fires when browser is waiting for data (buffering)
    audio.onwaiting = () => {
        setLoading(true);
    };

    audio.onerror = () => {
        setLoading(false);
        showStatus("Playback Error", true);
    };

    checkAuth().then(() => { loadView('home'); });
</script>
</body>
</html>
"""

# -----------------------------------------------------------------------------
# BACKEND LOGIC
# -----------------------------------------------------------------------------

class SpotifyProxy:
    BASE_URL = "https://api.spotify.com/v1"

    @staticmethod
    def get_headers():
        return {"Authorization": f"Bearer {auth_state['access_token']}"}

def sanitize_filename(name):
    """Remove invalid filename characters"""
    return "".join([c for c in name if c.isalnum() or c in (' ', '-', '_', '.')]).strip()[:200]

def set_metadata(filepath, title, artist, album, image_url):
    """Add ID3 tags and album art to MP3 file"""
    try:
        audio = MP3(filepath, ID3=ID3)
        
        if not audio.tags:
            audio.add_tags()
            
        audio.tags.add(TIT2(encoding=3, text=title))
        audio.tags.add(TPE1(encoding=3, text=artist))
        audio.tags.add(TALB(encoding=3, text=album or "Downloaded"))
        audio.tags.add(TCON(encoding=3, text="Spotify Downloader"))

        if image_url:
            try:
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
                }
                img_resp = requests.get(image_url, headers=headers, timeout=10)
                if img_resp.status_code == 200:
                    audio.tags.add(
                        APIC(
                            encoding=3,
                            mime='image/jpeg',
                            type=3,
                            desc='Cover',
                            data=img_resp.content
                        )
                    )
            except Exception as e:
                logging.warning(f"Failed to download album art from {image_url}: {e}")

        audio.save()
        logging.info(f"Metadata added for: {title}")
    except Exception as e:
        logging.error(f"Metadata tagging failed for {title}: {e}")

def get_cached_stream_url(video_id):
    """Check local file for cached stream URL"""
    try:
        with stream_cache_lock:
            if not os.path.exists(STREAM_CACHE_FILE):
                return None
            
            with open(STREAM_CACHE_FILE, 'r') as f:
                cache = json.load(f)
                return cache.get(video_id)
    except Exception as e:
        logging.error(f"Cache read error: {e}")
        return None

def save_stream_to_cache(video_id, url):
    """Save stream URL to local file"""
    try:
        with stream_cache_lock:
            cache = {}
            if os.path.exists(STREAM_CACHE_FILE):
                try:
                    with open(STREAM_CACHE_FILE, 'r') as f:
                        cache = json.load(f)
                except:
                    # If file is corrupted, start fresh
                    cache = {}
            
            cache[video_id] = url
            with open(STREAM_CACHE_FILE, 'w') as f:
                json.dump(cache, f)
                
            logging.info(f"Cached stream URL for {video_id}")
    except Exception as e:
        logging.error(f"Cache write error: {e}")

def get_youtube_stream_url(video_id):
    """Extract direct stream URL from YouTube video with server-side caching"""
    # 1. Check Cache first
    cached_url = get_cached_stream_url(video_id)
    if cached_url:
        logging.info(f"Stream URL found in cache for {video_id}")
        return cached_url

    # 2. If not in cache, fetch via yt-dlp
    try:
        url = f"https://www.youtube.com/watch?v={video_id}"
        ydl_opts = {
            'format': 'bestaudio/best',
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
            'noplaylist': True,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            stream_url = None
            
            # Try to find audio-only format
            for f in info.get('formats', []):
                if f.get('acodec') != 'none' and f.get('vcodec') == 'none':
                    stream_url = f['url']
                    break
            
            # Fallback to best available
            if not stream_url:
                for f in info.get('formats', []):
                    if f.get('acodec') != 'none':
                        stream_url = f['url']
                        break
            
            if stream_url:
                # 3. Save to cache for next time
                save_stream_to_cache(video_id, stream_url)
                return stream_url
            
            return None
    except Exception as e:
        logging.error(f"YT Stream Error: {e}")
        return None

def search_youtube(query):
    """Search YouTube and return 25 results"""
    try:
        ydl_opts = {
            'format': 'bestaudio/best',
            'quiet': True,
            'extract_flat': True,
            'noplaylist': True,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            result = ydl.extract_info(f"ytsearch25:{query}", download=False)
            if 'entries' in result:
                return [
                    {
                        'id': e.get('id'),
                        'title': e.get('title'),
                        'uploader': e.get('uploader', 'Unknown'),
                        'thumbnail': f"https://img.youtube.com/vi/{e.get('id')}/mqdefault.jpg",
                        'duration': e.get('duration')
                    } for e in result['entries'] if e
                ]
        return []
    except Exception as e:
        logging.error(f"YT Search Error: {e}")
        return []

class RequestHandler(SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        """Suppress default logging"""
        pass

    def end_headers(self):
        """Add CORS headers"""
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, Authorization')
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.end_headers()

    def safe_write(self, content):
        """Safely write response"""
        try:
            if isinstance(content, str):
                content = content.encode('utf-8')
            self.wfile.write(content)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass

    def do_GET(self):
        if self.path == '/':
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            self.safe_write(HTML_CONTENT)
        
        elif self.path.startswith('/callback'):
            query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            code = query.get('code', [None])[0]
            if code:
                try:
                    auth_str = base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()
                    resp = requests.post(
                        'https://accounts.spotify.com/api/token',
                        data={
                            "grant_type": "authorization_code",
                            "code": code,
                            "redirect_uri": REDIRECT_URI
                        },
                        headers={
                            "Authorization": f"Basic {auth_str}",
                            "Content-Type": "application/x-www-form-urlencoded"
                        },
                        timeout=10
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        auth_state['access_token'] = data['access_token']
                        auth_state['refresh_token'] = data.get('refresh_token')
                        auth_state['expires_at'] = time.time() + data['expires_in']
                        logging.info("Authentication successful")
                        self.send_response(302)
                        self.send_header('Location', '/')
                        self.end_headers()
                    else:
                        logging.error(f"Token exchange failed: {resp.status_code}")
                        self.send_error(500, "Failed to exchange token")
                except Exception as e:
                    logging.error(f"Auth callback error: {e}")
                    self.send_error(500, str(e))
            else:
                self.send_error(400, "No code provided")

        elif self.path == '/api/auth/login':
            scope = "user-library-read playlist-read-private playlist-read-collaborative user-top-read user-read-email"
            auth_url = f"https://accounts.spotify.com/authorize?client_id={CLIENT_ID}&response_type=code&redirect_uri={urllib.parse.quote(REDIRECT_URI)}&scope={urllib.parse.quote(scope)}"
            self.send_response(302)
            self.send_header('Location', auth_url)
            self.end_headers()

        elif self.path == '/api/auth/status':
            self.send_json({"logged_in": auth_state['access_token'] is not None, "token": auth_state['access_token']})
            
        elif self.path == '/api/auth/logout':
            auth_state['access_token'] = None
            auth_state['refresh_token'] = None
            logging.info("User logged out")
            self.send_response(302)
            self.send_header('Location', '/')
            self.end_headers()

        elif self.path.startswith('/api/spotify'):
            if '/me/tracks' in self.path:
                url = SpotifyProxy.BASE_URL + self.path.replace('/api/spotify', '')
                
                parsed_url = urllib.parse.urlparse(url)
                query_params = urllib.parse.parse_qs(parsed_url.query)
                query_params['limit'] = ['50']
                query_params['market'] = ['from_token'] 
                
                new_query = urllib.parse.urlencode(query_params, doseq=True)
                url = urllib.parse.urlunparse((parsed_url.scheme, parsed_url.netloc, parsed_url.path, parsed_url.params, new_query, parsed_url.fragment))

                all_items = []
                
                try:
                    resp = requests.get(url, headers=SpotifyProxy.get_headers(), timeout=10)
                    if resp.status_code != 200:
                        logging.error(f"Spotify API Error on /me/tracks: {resp.status_code} - {resp.text}")
                        self.send_response(resp.status_code)
                        self.send_header('Content-type', 'application/json')
                        self.end_headers()
                        self.safe_write(resp.content)
                        return

                    data = resp.json()
                    all_items.extend(data.get('items', []))
                    next_url = data.get('next')

                    while next_url:
                        time.sleep(0.1)
                        resp = requests.get(next_url, headers=SpotifyProxy.get_headers(), timeout=10)
                        if resp.status_code != 200:
                            logging.warning(f"Pagination failed at {next_url}: {resp.status_code}")
                            break
                        data = resp.json()
                        if 'items' in data:
                            all_items.extend(data['items'])
                        else:
                            break
                        next_url = data.get('next')
                    
                    self.send_response(200)
                    self.send_header('Content-type', 'application/json')
                    self.end_headers()
                    self.safe_write(json.dumps({"items": all_items, "total": len(all_items)}).encode('utf-8'))
                    return

                except Exception as e:
                    logging.error(f"Exception in liked songs fetch: {e}")
                    self.send_error(500, str(e))
                    return

            url = SpotifyProxy.BASE_URL + self.path.replace('/api/spotify', '')
            try:
                resp = requests.get(url, headers=SpotifyProxy.get_headers(), timeout=10)
                self.send_response(resp.status_code)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.safe_write(resp.content)
            except Exception as e:
                logging.error(f"Spotify proxy error: {e}")
                self.send_error(502, str(e))
        
        elif self.path == '/api/library':
            files = []
            try:
                for f in os.listdir(DOWNLOAD_DIR):
                    if f.endswith('.mp3'):
                        try:
                            path = os.path.join(DOWNLOAD_DIR, f)
                            audio = MP3(path)
                            title = str(audio.get('TIT2', [f.replace('.mp3', '')])[0])
                            artist = str(audio.get('TPE1', ['Unknown'])[0])
                            duration = audio.info.length
                            files.append({"title": title, "artist": artist, "path": path, "duration": duration})
                        except Exception as e:
                            logging.warning(f"Failed to read metadata from {f}: {e}")
                            files.append({"title": f.replace('.mp3', ''), "artist": "Unknown", "path": os.path.join(DOWNLOAD_DIR, f), "duration": 0})
            except Exception as e:
                logging.error(f"Library scan error: {e}")
            self.send_json(files)

        elif self.path.startswith('/api/files'):
            query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            raw_path = query.get('path', [None])[0]
            if raw_path:
                path = urllib.parse.unquote(raw_path)
            else:
                self.send_error(400)
                return

            real_path = os.path.realpath(path)
            real_download = os.path.realpath(DOWNLOAD_DIR)
            
            if os.path.exists(real_path) and real_path.startswith(real_download):
                try:
                    self.send_response(200)
                    if path.lower().endswith('.mp3'):
                        mime = 'audio/mpeg'
                    else:
                        mime = mimetypes.guess_type(path)[0] or 'audio/mpeg'
                    
                    self.send_header('Content-type', mime)
                    self.send_header('Accept-Ranges', 'bytes')
                    file_size = os.path.getsize(path)
                    self.send_header('Content-Length', str(file_size))
                    self.end_headers()
                    with open(path, 'rb') as f:
                        self.safe_write(f.read())
                except Exception as e:
                    logging.error(f"File serve error: {e}")
                    self.send_error(500)
            else:
                self.send_error(404)

        elif self.path.startswith('/api/cover'):
            query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            raw_path = query.get('path', [None])[0]
            if raw_path:
                path = urllib.parse.unquote(raw_path)
            else:
                self.send_error(400)
                return

            real_path = os.path.realpath(path)
            real_download = os.path.realpath(DOWNLOAD_DIR)
            
            if os.path.exists(real_path) and real_path.startswith(real_download):
                try:
                    audio = MP3(path)
                    apic_key = None
                    if 'APIC:' in audio:
                        apic_key = 'APIC:'
                    else:
                        for key in audio.keys():
                            if key.startswith('APIC'):
                                apic_key = key
                                break
                    
                    if apic_key:
                        apic = audio[apic_key]
                        img_data = apic.data
                        img_mime = apic.mime 
                        
                        self.send_response(200)
                        self.send_header('Content-type', img_mime)
                        self.send_header('Content-Length', str(len(img_data)))
                        self.end_headers()
                        self.safe_write(img_data)
                    else:
                        self.send_error(404)
                except Exception as e:
                    logging.error(f"Cover art extraction error: {e}")
                    self.send_error(500)
            else:
                self.send_error(404)
        
        elif self.path.startswith('/api/yt-stream'):
            query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            vid_id = query.get('id', [None])[0]
            if vid_id:
                stream_url = get_youtube_stream_url(vid_id)
                if stream_url:
                    self.send_json({"success": True, "url": stream_url})
                else:
                    self.send_json({"success": False, "error": "Stream not found"})
            else:
                self.send_error(400)

        elif self.path.startswith('/api/search-yt'):
            query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            q = query.get('q', [None])[0]
            if q:
                results = search_youtube(q)
                self.send_json({"success": True, "results": results})
            else:
                self.send_error(400)
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path == '/api/download':
            content_len = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_len)
            data = json.loads(post_data)
            
            title = sanitize_filename(data['title'])
            artist = sanitize_filename(data['artist'])
            image_url = data.get('imgUrl')
            youtube_id = data.get('youtube_id')
            
            filename = f"{artist} - {title}.mp3"
            filepath = os.path.join(DOWNLOAD_DIR, filename)

            if os.path.exists(filepath):
                self.send_json({"success": True, "message": "Already exists"})
                return

            def run_download():
                try:
                    ydl_opts = {
                        'format': 'bestaudio/best',
                        'postprocessors': [{
                            'key': 'FFmpegExtractAudio',
                            'preferredcodec': 'mp3',
                            'preferredquality': '192',
                        }],
                        'outtmpl': filepath.replace('.mp3', ''),
                        'quiet': True,
                        'no_warnings': True,
                    }
                    
                    if youtube_id:
                        url = f"https://www.youtube.com/watch?v={youtube_id}"
                        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                            ydl.extract_info(url, download=True)
                    else:
                        search_query = f"{title} {artist} official audio"
                        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                            ydl.extract_info(f"ytsearch:{search_query}", download=True)['entries'][0]
                    
                    set_metadata(filepath, title, artist, "", image_url)
                except Exception as e:
                    logging.error(f"Download failed: {e}")

            threading.Thread(target=run_download).start()
            self.send_json({"success": True, "message": "Download started"})

    def send_json(self, obj):
        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        try:
            self.wfile.write(json.dumps(obj).encode('utf-8'))
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass

class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    pass

def start_server():
    server = ThreadedHTTPServer(('0.0.0.0', PORT), RequestHandler)
    print(f"Serving at http://0.0.0.0:{PORT}")
    server.serve_forever()

if __name__ == '__main__':
    start_server()
