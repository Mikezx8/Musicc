import os
import spotipy
from spotipy.oauth2 import SpotifyOAuth
import yt_dlp
import threading
import time
import re
import json
import tempfile
import webview
from datetime import datetime
from pathlib import Path
import sys
import subprocess
import requests
from PIL import Image
import io
import imageio_ffmpeg
import base64
import pygame
import math
import numpy as np
from sklearn.metrics.pairwise import cosine_similarity
from collections import defaultdict
import pickle
import hashlib
import random

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='ignore')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='ignore')

# ============================================
# CONFIGURATION
# ============================================
# Define the base directory on the C drive
BASE_DIR = r"C:\Musicc"

# Ensure the base directory exists
if not os.path.exists(BASE_DIR):
    try:
        os.makedirs(BASE_DIR)
        print(f"Created directory: {BASE_DIR}")
    except PermissionError:
        print(f"⚠️ Permission denied: Cannot create {BASE_DIR}. Please run as Administrator.")
    except Exception as e:
        print(f"⚠️ Error creating directory: {e}")

DURATION_TOLERANCE = 20
# Output directory is now inside the Musicc folder
OUTPUT_DIR = os.path.join(BASE_DIR, "downloaded_music")
TRACKS_PER_PAGE = 50
MAX_TRACKS = 5000

# Spotify Configuration
CLIENT_ID = "SET_ID_HERE"
CLIENT_SECRET = "SET_SECRET_HERE"
REDIRECT_URI = "https://dragon-surround-fly-revised.trycloudflare.com/callback"
SCOPE = "user-library-read playlist-read-private playlist-read-collaborative"

# Default settings
DEFAULT_SETTINGS = {
    "download_as_mp3": True,
    "embed_thumbnail": True,
    "save_cover_separately": False,
    "mp3_quality": "2",  # 0-9, lower is better
    "output_dir": OUTPUT_DIR, # Pointing to C:\Musicc\downloaded_music
    "volume": 0.7  # Default volume (0.0 to 1.0)
}

# ============================================
# MEDIA PLAYER CLASS
# ============================================
class MediaPlayer:
    def __init__(self):
        pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=4096)
        self.current_track = None
        self.is_playing = False
        self.is_paused = False
        self.volume = DEFAULT_SETTINGS["volume"]
        self.duration = 0
        self.position = 0
        self.last_update_time = 0
        self.update_thread = None
        self.should_update = False
        self.temp_file = None
        
    def load_track(self, filepath):
        """Load a track for playback"""
        try:
            file_ext = os.path.splitext(filepath)[1].lower()
            
            pygame_supported = file_ext in ['.mp3', '.wav', '.ogg', '.webm', '.mid', '.midi']
            
            if not pygame_supported:
                try:
                    from pydub import AudioSegment
                    
                    import tempfile
                    temp_dir = tempfile.mkdtemp()
                    temp_wav = os.path.join(temp_dir, 'temp.wav')
                    
                    audio = AudioSegment.from_file(filepath)
                    audio.export(temp_wav, format='wav')
                    
                    pygame.mixer.music.load(temp_wav)
                    self.temp_file = temp_wav
                    
                except ImportError:
                    print(f"⚠️ Can't play {file_ext} files. Install pydub: pip install pydub")
                    return False
                except Exception as e:
                    print(f"Error converting {file_ext} to WAV: {e}")
                    return False
            else:
                if pygame.mixer.music.get_busy():
                    pygame.mixer.music.stop()
                
                pygame.mixer.music.load(filepath)
            
            self.current_track = filepath
            self.is_playing = False
            self.is_paused = False
            self.position = 0
            
            try:
                file_ext = os.path.splitext(filepath)[1].lower()
                if file_ext == '.mp3':
                    from mutagen.mp3 import MP3
                    audio = MP3(filepath)
                    self.duration = audio.info.length
                elif file_ext == '.m4a':
                    from mutagen.mp4 import MP4
                    audio = MP4(filepath)
                    self.duration = audio.info.length
                elif file_ext == '.flac':
                    from mutagen.flac import FLAC
                    audio = FLAC(filepath)
                    self.duration = audio.info.length
                elif file_ext == '.webm':
                    try:
                        from pydub import AudioSegment
                        audio = AudioSegment.from_file(filepath)
                        self.duration = len(audio) / 1000.0
                    except:
                        self.duration = 180
                else:
                    self.duration = 180
            except Exception as e:
                print(f"Could not get duration for {filepath}: {e}")
                self.duration = 180
            
            pygame.mixer.music.set_volume(self.volume)
            return True
        except Exception as e:
            print(f"Error loading track {filepath}: {e}")
            return False
    
    def play(self):
        """Play the loaded track"""
        try:
            pygame.mixer.music.play()
            self.is_playing = True
            self.is_paused = False
            self.start_position_update()
            return True
        except Exception as e:
            print(f"Error playing track: {e}")
            return False
    
    def pause(self):
        """Pause playback"""
        try:
            pygame.mixer.music.pause()
            self.is_paused = True
            self.is_playing = False
            return True
        except Exception as e:
            print(f"Error pausing track: {e}")
            return False
    
    def unpause(self):
        """Resume playback"""
        try:
            pygame.mixer.music.unpause()
            self.is_paused = False
            self.is_playing = True
            return True
        except Exception as e:
            print(f"Error unpausing track: {e}")
            return False
    
    def stop(self):
        """Stop playback"""
        try:
            pygame.mixer.music.stop()
            self.is_playing = False
            self.is_paused = False
            self.position = 0
            self.stop_position_update()
            return True
        except Exception as e:
            print(f"Error stopping track: {e}")
            return False
    
    def set_volume(self, volume):
        """Set volume level (0.0 to 1.0)"""
        try:
            self.volume = max(0.0, min(1.0, volume))
            pygame.mixer.music.set_volume(self.volume)
            return True
        except Exception as e:
            print(f"Error setting volume: {e}")
            return False
    
    def set_position(self, position):
        """Set playback position in seconds"""
        try:
            position = max(0, min(self.duration, position))
            pygame.mixer.music.set_pos(position)
            self.position = position
            return True
        except Exception as e:
            print(f"Error setting position: {e}")
            return False
    
    def get_position(self):
        """Get current playback position"""
        if not self.is_playing and not self.is_paused:
            return self.position
        
        try:
            current_time = time.time()
            if self.last_update_time > 0:
                time_elapsed = current_time - self.last_update_time
                if self.is_playing and not self.is_paused:
                    self.position = min(self.duration, self.position + time_elapsed)
            self.last_update_time = current_time
            return self.position
        except:
            return self.position
    
    def start_position_update(self):
        """Start thread to update playback position"""
        self.should_update = True
        self.last_update_time = time.time()
        if self.update_thread is None or not self.update_thread.is_alive():
            self.update_thread = threading.Thread(target=self._update_position, daemon=True)
            self.update_thread.start()
    
    def stop_position_update(self):
        """Stop the position update thread"""
        self.should_update = False
    
    def _update_position(self):
        """Update playback position in background"""
        while self.should_update:
            if self.is_playing and not self.is_paused:
                current_time = time.time()
                if self.last_update_time > 0:
                    time_elapsed = current_time - self.last_update_time
                    self.position = min(self.duration, self.position + time_elapsed)
                self.last_update_time = current_time
            
            if not pygame.mixer.music.get_busy() and self.is_playing:
                self.is_playing = False
                self.position = self.duration
                break
            
            time.sleep(0.1)
    
    def get_playback_info(self):
        """Get current playback information"""
        return {
            "is_playing": self.is_playing,
            "is_paused": self.is_paused,
            "volume": self.volume,
            "position": self.get_position(),
            "duration": self.duration,
            "current_track": self.current_track
        }

# ============================================
# MUSIC CLASSIFIER & RECOMMENDATION ENGINE
# ============================================
class MusicClassifier:
    def __init__(self):
        self.genres = [
            'hiphop', 'indie', 'drill', 'sad', 'breakup', 'phonk', 
            'jumpstyle', 'electronic', 'pop', 'rock', 'jazz', 'rnb',
            'afrobeats', 'reggae', 'dancehall', 'kpop', 'metal',
            'classical', 'lofi', 'ambient', 'folk', 'country', 'blues',
            'punk', 'house', 'techno', 'trance', 'dubstep', 'trap',
            'soul', 'funk', 'disco', 'gospel', 'opera', 'reggaeton'
        ]
        
        self.genre_keywords = {
            'hiphop': ['rap', 'hip hop', 'hip-hop', 'rapper'],
            'indie': ['indie', 'alternative', 'bedroom pop'],
            'drill': ['drill', 'uk drill', 'brooklyn drill'],
            'sad': ['sad', 'emotional', 'melancholy', 'depressing'],
            'breakup': ['breakup', 'heartbreak', 'love gone'],
            'phonk': ['phonk', 'memphis', 'cowbell'],
            'jumpstyle': ['jumpstyle', 'hardstyle', 'gabber'],
            'electronic': ['electronic', 'edm', 'synth'],
            'pop': ['pop', 'mainstream', 'top 40'],
            'rock': ['rock', 'guitar', 'band'],
            'jazz': ['jazz', 'swing', 'bebop'],
            'rnb': ['r&b', 'rnb', 'rhythm and blues'],
            'afrobeats': ['afrobeats', 'afrobeat', 'afropop'],
            'reggae': ['reggae', 'dancehall', 'ska'],
            'lofi': ['lofi', 'lo-fi', 'chillhop'],
            'ambient': ['ambient', 'background', 'atmospheric'],
            'metal': ['metal', 'heavy metal', 'death metal'],
            'classical': ['classical', 'orchestral', 'symphony']
        }
        
        self.user_profile = None
        self.track_vectors = {}
        self.play_history = []
        self.genre_stats = defaultdict(int)
        self.load_user_profile()
    
    def load_user_profile(self):
        """Load user listening profile"""
        try:
            profile_file = os.path.join(BASE_DIR, "user_music_profile.pkl")
            if os.path.exists(profile_file):
                with open(profile_file, 'rb') as f:
                    data = pickle.load(f)
                    self.user_profile = data.get('profile_vector')
                    self.play_history = data.get('play_history', [])
                    self.genre_stats = data.get('genre_stats', defaultdict(int))
                print(f"✅ Loaded user profile with {len(self.play_history)} plays")
        except Exception as e:
            print(f"Could not load user profile: {e}")
            self.user_profile = np.zeros(len(self.genres) + 5)
    
    def save_user_profile(self):
        """Save user listening profile"""
        try:
            profile_file = os.path.join(BASE_DIR, "user_music_profile.pkl")
            data = {
                'profile_vector': self.user_profile,
                'play_history': self.play_history[-1000:],
                'genre_stats': self.genre_stats
            }
            with open(profile_file, 'wb') as f:
                pickle.dump(data, f)
        except Exception as e:
            print(f"Could not save user profile: {e}")
    
    def extract_features(self, track):
        """Extract features from track metadata"""
        genre_vector = np.zeros(len(self.genres))
        
        text = f"{track.get('title', '')} {track.get('artist', '')} {track.get('album', '')}".lower()
        
        for idx, genre in enumerate(self.genres):
            if genre in text:
                genre_vector[idx] = 1
            elif genre in self.genre_keywords:
                for keyword in self.genre_keywords[genre]:
                    if keyword in text:
                        genre_vector[idx] = 1
                        break
        
        features = np.array([
            track.get('popularity', 50) / 100,
            min(track.get('duration', 180) / 300, 1),
            random.random() * 0.5,
            random.random() * 0.5,
            random.random() * 0.5,
        ])
        
        return np.concatenate([genre_vector, features])
    
    def update_user_profile(self, track_vector, weight=0.1):
        """Update user profile based on played track"""
        if self.user_profile is None:
            self.user_profile = track_vector
        else:
            self.user_profile = (1 - weight) * self.user_profile + weight * track_vector
        
        for idx, genre in enumerate(self.genres):
            if track_vector[idx] > 0.5:
                self.genre_stats[genre] += 1
        
        self.save_user_profile()
    
    def log_play(self, track):
        """Log a track play"""
        track_id = f"{track['artist']}_{track['title']}"
        self.play_history.append({
            'track_id': track_id,
            'timestamp': time.time(),
            'track': track
        })
        
        features = self.extract_features(track)
        self.track_vectors[track_id] = features
        self.update_user_profile(features)
        
        if len(self.play_history) > 1000:
            self.play_history = self.play_history[-1000:]
    
    def get_top_genres(self, n=5):
        """Get user's top n genres"""
        sorted_genres = sorted(self.genre_stats.items(), key=lambda x: x[1], reverse=True)
        return [genre for genre, count in sorted_genres[:n]]
    
    def recommend_based_on_profile(self, all_tracks, n=6):
        """Recommend tracks based on user profile"""
        if self.user_profile is None or len(all_tracks) == 0:
            return []
        
        track_ids = []
        vectors = []
        
        for track in all_tracks:
            track_id = f"{track['artist']}_{track['title']}"
            if track_id in self.track_vectors:
                vectors.append(self.track_vectors[track_id])
            else:
                vectors.append(self.extract_features(track))
            track_ids.append(track_id)
        
        if not vectors:
            return []
        
        profile_vector = self.user_profile.reshape(1, -1)
        similarities = cosine_similarity(profile_vector, vectors)[0]
        
        top_indices = similarities.argsort()[-n:][::-1]
        
        recommendations = []
        for idx in top_indices:
            if idx < len(all_tracks):
                recommendations.append(all_tracks[idx])
        
        return recommendations
    
    def search_tracks_by_genre(self, tracks, genre_query):
        """Search tracks by genre combination"""
        if not genre_query:
            return tracks
        
        positive = []
        negative = []
        
        for term in genre_query.lower().split():
            if term.startswith('-'):
                negative.append(term[1:])
            elif term.startswith('+'):
                positive.append(term[1:])
            else:
                positive.append(term)
        
        results = []
        for track in tracks:
            text = f"{track['title']} {track['artist']} {track['album']}".lower()
            
            skip = False
            for neg in negative:
                if neg in text:
                    skip = True
                    break
            if skip:
                continue
            
            match = True
            for pos in positive:
                if pos not in text and pos not in self.genre_keywords:
                    found = False
                    for keyword in self.genre_keywords.get(pos, []):
                        if keyword in text:
                            found = True
                            break
                    if not found:
                        match = False
                        break
            
            if match:
                results.append(track)
        
        return results

# ============================================
# PLAYLIST MANAGER
# ============================================
class PlaylistManager:
    def __init__(self):
        self.playlists_file = os.path.join(BASE_DIR, "playlists.json")
        self.playlists = self.load_playlists()
        
    def load_playlists(self):
        """Load playlists from file"""
        try:
            if os.path.exists(self.playlists_file):
                with open(self.playlists_file, 'r') as f:
                    return json.load(f)
        except Exception as e:
            print(f"Error loading playlists: {e}")
        
        return {
            "Downloads": {
                "name": "Downloads",
                "description": "Downloaded music",
                "type": "downloads",
                "path": OUTPUT_DIR,
                "tracks": [],
                "created_at": datetime.now().isoformat()
            },
            "Favorites": {
                "name": "Favorites",
                "description": "Your favorite tracks",
                "type": "virtual",
                "tracks": [],
                "created_at": datetime.now().isoformat()
            }
        }
    
    def save_playlists(self):
        """Save playlists to file"""
        try:
            with open(self.playlists_file, 'w') as f:
                json.dump(self.playlists, f, indent=2)
            return True
        except Exception as e:
            print(f"Error saving playlists: {e}")
            return False
    
    def create_playlist(self, name, folder_path=None, description=""):
        """Create a new playlist - UPDATED VERSION"""
        try:
            if not name or name.strip() == "":
                return False
            
            name = name.strip()
            
            # Check if playlist already exists
            if name in self.playlists:
                return False
            
            # Create playlist structure
            self.playlists[name] = {
                "name": name,
                "description": description,
                "type": "folder" if folder_path else "virtual",
                "path": folder_path,
                "tracks": [],  # Make sure tracks array is initialized
                "created_at": datetime.now().isoformat(),
                "last_updated": datetime.now().isoformat()
            }
            
            # Create folder if specified
            if folder_path:
                os.makedirs(folder_path, exist_ok=True)
                print(f"Created folder for playlist: {folder_path}")
            
            # Save to file
            if self.save_playlists():
                print(f"Playlist '{name}' created successfully")
                return True
            
            return False
        except Exception as e:
            print(f"Error creating playlist: {e}")
            return False
    
    def delete_playlist(self, name):
        """Delete a playlist"""
        if name not in self.playlists or name in ["Downloads", "Favorites"]:
            return False
        
        del self.playlists[name]
        return self.save_playlists()
    
    def add_to_playlist(self, playlist_name, track):
        """Add a track to playlist"""
        if playlist_name not in self.playlists:
            return False
        
        for existing in self.playlists[playlist_name]["tracks"]:
            if existing.get("title") == track.get("title") and \
               existing.get("artist") == track.get("artist"):
                return False
        
        self.playlists[playlist_name]["tracks"].append(track)
        return self.save_playlists()
    
    def remove_from_playlist(self, playlist_name, track_index):
        """Remove a track from playlist"""
        if playlist_name not in self.playlists:
            return False
        
        if 0 <= track_index < len(self.playlists[playlist_name]["tracks"]):
            del self.playlists[playlist_name]["tracks"][track_index]
            return self.save_playlists()
        
        return False
    
    def scan_folder_playlist(self, playlist_name):
        """Scan folder for playlist"""
        if playlist_name not in self.playlists:
            return []
        
        playlist = self.playlists[playlist_name]
        if playlist["type"] != "folder" or not playlist.get("path"):
            return playlist.get("tracks", [])
        
        folder_path = playlist["path"]
        if not os.path.exists(folder_path):
            return []
        
        tracks = []
        for file in os.listdir(folder_path):
            if file.endswith(('.mp3', '.m4a', '.webm', '.flac', '.ogg')):
                filename = os.path.splitext(file)[0]
                parts = filename.split(' - ', 1)
                if len(parts) == 2:
                    artist, title = parts
                    
                    audio_file = os.path.join(folder_path, file)
                    thumbnail = get_embedded_cover(audio_file)
                    thumbnail_data = image_to_base64(thumbnail) if thumbnail else None
                    
                    duration = 0
                    try:
                        file_ext = os.path.splitext(audio_file)[1].lower()
                        if file_ext == '.mp3':
                            from mutagen.mp3 import MP3
                            audio = MP3(audio_file)
                            duration = audio.info.length
                    except:
                        pass
                    
                    tracks.append({
                        "title": title,
                        "artist": artist,
                        "filepath": audio_file,
                        "thumbnail": thumbnail_data,
                        "duration": duration,
                        "duration_str": format_time(duration),
                        "filename": file
                    })
        
        playlist["tracks"] = tracks
        self.save_playlists()
        return tracks
    
    def get_playlist_tracks(self, playlist_name):
        """Get tracks from playlist"""
        if playlist_name not in self.playlists:
            return []
        
        playlist = self.playlists[playlist_name]
        
        if playlist["type"] == "folder":
            return self.scan_folder_playlist(playlist_name)
        else:
            return playlist.get("tracks", [])
    
    def get_all_playlists(self):
        """Get all playlist names"""
        return list(self.playlists.keys())

# ============================================
# UTILITY FUNCTIONS
# ============================================
def clean_filename(text):
    """Clean text for use in filenames"""
    text = re.sub(r'[<>:"/\\|?*]', '', text)
    text = re.sub(r'\s+', ' ', text)
    if len(text) > 100:
        text = text[:97] + "..."
    return text.strip()

def download_thumbnail(url, temp_dir):
    """Download thumbnail image and return its path"""
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        
        image = Image.open(io.BytesIO(response.content))
        
        if image.mode != 'RGB':
            image = image.convert('RGB')
        
        max_size = 1000
        if max(image.size) > max_size:
            ratio = max_size / max(image.size)
            new_size = tuple(int(dim * ratio) for dim in image.size)
            image = image.resize(new_size, Image.Resampling.LANCZOS)
        
        thumbnail_path = os.path.join(temp_dir, "cover.jpg")
        image.save(thumbnail_path, "JPEG", quality=95)
        return thumbnail_path
        
    except Exception as e:
        print(f"Error downloading thumbnail: {e}")
        return None

def get_embedded_cover(audio_file):
    """Extract embedded cover art from audio file"""
    try:
        file_ext = os.path.splitext(audio_file)[1].lower()
        
        if file_ext == '.webm':
            return None
            
        if file_ext == '.mp3':
            try:
                from mutagen.mp3 import MP3
                from mutagen.id3 import ID3
                
                try:
                    audio = MP3(audio_file, ID3=ID3)
                except:
                    audio = MP3(audio_file)
                
                if hasattr(audio, 'tags') and audio.tags:
                    for tag in audio.tags.values():
                        if hasattr(tag, 'mime') and tag.mime and tag.mime.startswith('image/'):
                            import tempfile
                            temp_dir = tempfile.mkdtemp()
                            cover_path = os.path.join(temp_dir, 'cover.jpg')
                            with open(cover_path, 'wb') as f:
                                f.write(tag.data)
                            return cover_path
            except Exception as e:
                pass
                
        elif file_ext == '.m4a':
            try:
                from mutagen.mp4 import MP4
                
                audio = MP4(audio_file)
                if 'covr' in audio:
                    import tempfile
                    temp_dir = tempfile.mkdtemp()
                    cover_path = os.path.join(temp_dir, 'cover.jpg')
                    with open(cover_path, 'wb') as f:
                        f.write(audio['covr'][0])
                    return cover_path
            except:
                pass
        
        return None
                
    except Exception as e:
        return None

def image_to_base64(image_path):
    """Convert image to base64 data URL"""
    try:
        if image_path and os.path.exists(image_path):
            with open(image_path, 'rb') as f:
                image_data = f.read()
                encoded = base64.b64encode(image_data).decode('utf-8')
                return f"data:image/jpeg;base64,{encoded}"
    except Exception as e:
        print(f"Error converting image to base64: {e}")
    return None

def format_time(seconds):
    """Format seconds to MM:SS or HH:MM:SS"""
    if not seconds or math.isnan(seconds):
        return "0:00"
    
    seconds = int(seconds)
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    
    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    else:
        return f"{minutes}:{secs:02d}"

def find_youtube_url(track_title, track_artist, spotify_duration):
    """Find YouTube URL for a track"""
    queries = [
        f"{track_artist} {track_title} official audio",
        f"{track_artist} {track_title} lyrics",
        f"{track_artist} {track_title}",
        f"{track_title} {track_artist}"
    ]
    
    ydl_opts = {
        "format": "bestaudio/best",
        "quiet": True,
        "skip_download": True,
        "noplaylist": True,
        "no_warnings": True,
        "extract_flat": True,
        "socket_timeout": 10,
    }
    
    for query in queries:
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                search_result = ydl.extract_info(f"ytsearch3:{query}", download=False)
                if not search_result or "entries" not in search_result:
                    continue
                
                for entry in search_result["entries"]:
                    if not entry:
                        continue
                    
                    video_duration = entry.get("duration", 0)
                    if video_duration and abs(video_duration - spotify_duration) <= DURATION_TOLERANCE:
                        return entry.get("url")
                        
        except Exception as e:
            print(f"Error searching for {query}: {e}")
            continue
    
    return None

def get_ffmpeg_path():
    """Get ffmpeg executable path"""
    try:
        return imageio_ffmpeg.get_ffmpeg_exe()
    except:
        return "ffmpeg"

def convert_with_ffmpeg(input_file, output_file, settings, thumbnail_path=None):
    """Convert audio file using ffmpeg with optional thumbnail embedding"""
    try:
        ffmpeg = get_ffmpeg_path()
        
        if not os.path.exists(ffmpeg):
            print(f"❌ FFmpeg not found at: {ffmpeg}")
            return False
        
        cmd = [ffmpeg, "-i", input_file]
        
        if thumbnail_path and settings["embed_thumbnail"] and os.path.exists(thumbnail_path):
            cmd.extend(["-i", thumbnail_path])
        
        if thumbnail_path and settings["embed_thumbnail"]:
            cmd.extend(["-map", "0:a", "-map", "1:v"])
        else:
            cmd.extend(["-map", "0:a"])
        
        if settings["download_as_mp3"]:
            cmd.extend([
                "-c:a", "libmp3lame",
                "-q:a", settings["mp3_quality"]
            ])
        else:
            cmd.extend(["-c:a", "copy"])
        
        if thumbnail_path and settings["embed_thumbnail"]:
            cmd.extend([
                "-c:v", "mjpeg",
                "-id3v2_version", "3",
                "-metadata:s:v", "title=Album cover",
                "-metadata:s:v", "comment=Cover (front)",
                "-disposition:v", "attached_pic"
            ])
        
        cmd.extend([
            "-metadata", f"title={settings.get('title', 'Unknown')}",
            "-metadata", f"artist={settings.get('artist', 'Unknown')}",
            "-metadata", f"album={settings.get('album', 'Unknown Album')}",
            "-y",
            output_file
        ])
        
        print(f"Running FFmpeg command: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        
        if result.returncode == 0:
            print(f"✅ FFmpeg conversion successful: {output_file}")
            return True
        else:
            print(f"❌ FFmpeg error: {result.stderr[:200]}")
            return False
            
    except subprocess.TimeoutExpired:
        print("❌ Conversion timed out")
        return False
    except Exception as e:
        print(f"❌ Conversion error: {e}")
        return False

def save_cover_separately(thumbnail_path, output_dir, artist, title):
    """Save cover image as separate file"""
    try:
        if thumbnail_path and os.path.exists(thumbnail_path):
            safe_artist = clean_filename(artist)
            safe_title = clean_filename(title)
            cover_filename = f"{safe_artist} - {safe_title}.jpg"
            cover_path = os.path.join(output_dir, cover_filename)
            
            import shutil
            shutil.copy2(thumbnail_path, cover_path)
            print(f"✅ Cover saved separately: {cover_path}")
            return True
    except Exception as e:
        print(f"Error saving cover separately: {e}")
    return False

def download_track(track, settings, progress_callback=None):
    """Download track with configurable settings"""
    temp_dir = None
    original_file = None
    
    try:
        youtube_url = find_youtube_url(track["title"], track["artist"], track["duration"])
        if not youtube_url:
            if progress_callback:
                progress_callback(f"❌ No valid audio found for: {track['artist']} - {track['title']}", "error")
            return False
        
        temp_dir = tempfile.mkdtemp()
        
        output_dir = settings.get("output_dir", OUTPUT_DIR)
        os.makedirs(output_dir, exist_ok=True)
        
        safe_artist = clean_filename(track["artist"])
        safe_title = clean_filename(track["title"])
        filename = f"{safe_artist} - {safe_title}"
        output_path = os.path.join(output_dir, filename)
        
        thumbnail_path = None
        if track.get("thumbnail"):
            thumbnail_path = download_thumbnail(track["thumbnail"], temp_dir)
        
        if progress_callback:
            progress_callback(f"⬇️ Downloading audio for: {track['artist']} - {track['title']}", "info")
        
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': os.path.join(temp_dir, 'audio.%(ext)s'),
            'quiet': True,
            'no_warnings': False,
            'writethumbnail': False,
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(youtube_url, download=True)
            downloaded_file = ydl.prepare_filename(info)
        
        original_file = downloaded_file
        print(f"Downloaded audio to: {original_file}")
        
        output_ext = ".mp3" if settings["download_as_mp3"] else os.path.splitext(original_file)[1]
        final_output = output_path + output_ext
        
        track_info = {
            "title": track["title"],
            "artist": track["artist"],
            "album": track.get("album", "Unknown Album")
        }
        
        if progress_callback:
            progress_callback(f"🔄 Processing: {track['artist']} - {track['title']}", "info")
        
        success = convert_with_ffmpeg(
            original_file, 
            final_output, 
            settings, 
            thumbnail_path
        )
        
        if not success:
            if progress_callback:
                progress_callback(f"⚠️ FFmpeg failed, using original file", "warning")
            import shutil
            shutil.copy2(original_file, final_output)
        
        if settings["save_cover_separately"] and thumbnail_path:
            save_cover_separately(thumbnail_path, output_dir, track["artist"], track["title"])
        
        if progress_callback:
            status_msg = f"✅ Downloaded: {track['artist']} - {track['title']}"
            if settings["download_as_mp3"]:
                status_msg += " [MP3]"
            if settings["embed_thumbnail"] and thumbnail_path:
                status_msg += " [Cover embedded]"
            if settings["save_cover_separately"] and thumbnail_path:
                status_msg += " [Cover saved separately]"
            progress_callback(status_msg, "success")
        
        return True
        
    except Exception as e:
        error_msg = str(e)
        if progress_callback:
            progress_callback(f"❌ Failed: {track['artist']} - {track['title']} ({error_msg[:50]})", "error")
        print(f"Download error: {e}")
        return False
    finally:
        if temp_dir and os.path.exists(temp_dir):
            try:
                import shutil
                shutil.rmtree(temp_dir)
            except:
                pass

# ============================================
# SETTINGS MANAGEMENT
# ============================================
class SettingsManager:
    def __init__(self):
        self.settings_file = os.path.join(BASE_DIR, "noir_settings.json")
        self.settings = self.load_settings()
    
    def load_settings(self):
        """Load settings from file or use defaults"""
        try:
            if os.path.exists(self.settings_file):
                with open(self.settings_file, 'r') as f:
                    loaded = json.load(f)
                    settings = DEFAULT_SETTINGS.copy()
                    settings.update(loaded)
                    return settings
        except Exception as e:
            print(f"Error loading settings: {e}")
        
        return DEFAULT_SETTINGS.copy()
    
    def save_settings(self):
        """Save settings to file"""
        try:
            with open(self.settings_file, 'w') as f:
                json.dump(self.settings, f, indent=2)
            return True
        except Exception as e:
            print(f"Error saving settings: {e}")
            return False
    
    def update_setting(self, key, value):
        """Update a single setting"""
        if key in self.settings:
            self.settings[key] = value
            return self.save_settings()
        return False
    
    def get_setting(self, key, default=None):
        """Get a setting value"""
        return self.settings.get(key, default)

# ============================================
# SPOTIFY CLIENT (FIXED - SINGLE WINDOW)
# ============================================
class SpotifyClient:
    def __init__(self):
        self.sp = None
        self.total_tracks = 0
        self.loaded_tracks = 0
        self.current_offset = 0
        self.auth_in_progress = False  # Track if auth is already happening
        self.auth_lock = threading.Lock()  # Lock to prevent concurrent auth
    
    def init_client(self):
        """Initialize Spotify client with GUI redirect handling"""
        with self.auth_lock:  # Prevent multiple concurrent auth attempts
            if self.auth_in_progress:
                print("⚠️ Spotify authentication already in progress")
                return False
            
            self.auth_in_progress = True
            try:
                return self._init_client_internal()
            finally:
                self.auth_in_progress = False
    
    def _init_client_internal(self):
        """Internal method to initialize client"""
        try:
            # Check for existing token cache
            cache_path = os.path.join(BASE_DIR, ".spotify_cache")
            
            # Try to load existing token first
            try:
                if os.path.exists(cache_path):
                    with open(cache_path, 'r') as f:
                        token_info = json.load(f)
                    
                    # Check if token is expired
                    import time
                    
                    expires_at = token_info.get('expires_at', 0)
                    current_time = time.time()
                    
                    if current_time < expires_at - 60:  # 60 second buffer
                        self.sp = spotipy.Spotify(auth=token_info['access_token'])
                        # Test the connection
                        self.sp.current_user()
                        print("✅ Using cached Spotify token")
                        return True
                    else:
                        print("⚠️ Cached token expired")
                        # Try to refresh
                        if 'refresh_token' in token_info:
                            refreshed = self.refresh_token(token_info['refresh_token'])
                            if refreshed:
                                return True
                        
                        # Clear invalid cache
                        os.remove(cache_path)
            except Exception as e:
                print(f"❌ Cached token invalid: {e}")
                # Clear the invalid cache
                if os.path.exists(cache_path):
                    os.remove(cache_path)
            
            # Need new authentication
            print("🔑 Starting Spotify authentication...")
            
            # Create auth URL
            auth_url = self.get_spotify_auth_url()
            
            # Use SIMPLE GUI - No separate window, just terminal input
            return self.simple_gui_auth(auth_url)
                
        except Exception as e:
            print(f"Spotify auth error: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def simple_gui_auth(self, auth_url):
        """Simple GUI auth that doesn't conflict with main window"""
        import webbrowser
        
        try:
            # Try to open browser
            print(f"\n🌐 Opening browser for Spotify authentication...")
            try:
                webbrowser.open(auth_url)
                print("✅ Browser opened with Spotify login")
            except:
                print(f"📋 If browser doesn't open, visit this URL manually:")
                print(f"   {auth_url}")
            
            print("\n" + "="*60)
            print("📝 AUTHENTICATION STEPS:")
            print("1. Log in to Spotify (if not already logged in)")
            print("2. Click 'AGREE' to authorize NOIR Player")
            print("3. You'll be redirected to a URL (may show error page)")
            print("4. Copy the ENTIRE URL from browser address bar")
            print("="*60 + "\n")
            
            # Check if we're in a GUI environment and create window if possible
            try:
                # Try to use tkinter for GUI input
                from tkinter import Tk, simpledialog
                
                # Create root window only if it doesn't exist
                try:
                    root = Tk()
                    root.withdraw()  # Hide the main window
                    root.attributes('-topmost', True)  # Make sure it's on top
                    
                    # Ask for the redirect URL
                    redirect_url = simpledialog.askstring(
                        "Spotify Authentication",
                        "Paste the redirect URL from your browser:",
                        parent=root
                    )
                    
                    root.destroy()  # Clean up the window
                except Exception as e:
                    print(f"⚠️ Tkinter error: {e}, falling back to terminal")
                    redirect_url = self.terminal_input()
                    
            except ImportError:
                # tkinter not available, use terminal
                print("⚠️ Tkinter not available, using terminal input")
                redirect_url = self.terminal_input()
            
            if not redirect_url:
                print("❌ Authentication cancelled")
                return False
            
            # Extract code from URL
            import urllib.parse
            parsed = urllib.parse.urlparse(redirect_url)
            params = urllib.parse.parse_qs(parsed.query)
            
            if 'code' in params and params['code']:
                code = params['code'][0]
                print("✅ Got authorization code")
                
                # Exchange code for token
                success = self.exchange_code_for_token(code)
                return success
            else:
                print("❌ No authorization code found in URL")
                return False
                
        except Exception as e:
            print(f"Error in GUI auth: {e}")
            # Fallback to manual terminal input
            return self.terminal_auth_fallback(auth_url)
    
    def terminal_input(self):
        """Get input from terminal"""
        print("\n📝 Paste the redirect URL below:")
        print("(Press Enter when done, Ctrl+C to cancel)")
        print("-" * 60)
        
        try:
            # Read multi-line input in case URL is long
            import sys
            if sys.platform == "win32":
                # Windows doesn't have readline, use simple input
                return input("URL: ").strip()
            else:
                # Try to use readline for better input
                import readline
                return input("URL: ").strip()
        except KeyboardInterrupt:
            print("\n❌ Cancelled")
            return None
        except Exception as e:
            print(f"❌ Input error: {e}")
            return None
    
    def terminal_auth_fallback(self, auth_url):
        """Fallback to terminal if GUI fails"""
        print("\n" + "="*60)
        print("GUI AUTH FAILED - USING TERMINAL")
        print("="*60)
        print(f"\n📋 Open this URL in your browser:")
        print(f"   {auth_url}")
        
        try:
            import webbrowser
            webbrowser.open(auth_url)
        except:
            pass
        
        redirect_url = self.terminal_input()
        
        if not redirect_url:
            print("❌ Authentication cancelled")
            return False
        
        # Extract code
        import urllib.parse
        parsed = urllib.parse.urlparse(redirect_url)
        params = urllib.parse.parse_qs(parsed.query)
        
        if 'code' in params and params['code']:
            code = params['code'][0]
            print("✅ Got authorization code")
            return self.exchange_code_for_token(code)
        else:
            print("❌ No authorization code found")
            return False
    
    def refresh_token(self, refresh_token):
        """Refresh an expired access token"""
        import requests
        import base64
        import time
        
        try:
            # Encode client credentials
            client_creds = f"{CLIENT_ID}:{CLIENT_SECRET}"
            encoded_creds = base64.b64encode(client_creds.encode()).decode()
            
            # Request new token
            token_url = "https://accounts.spotify.com/api/token"
            headers = {
                'Authorization': f'Basic {encoded_creds}',
                'Content-Type': 'application/x-www-form-urlencoded'
            }
            
            data = {
                'grant_type': 'refresh_token',
                'refresh_token': refresh_token
            }
            
            response = requests.post(token_url, headers=headers, data=data)
            response.raise_for_status()
            
            token_info = response.json()
            
            # Add refresh token back if not included
            if 'refresh_token' not in token_info:
                token_info['refresh_token'] = refresh_token
            
            # Calculate expires_at
            token_info['expires_at'] = time.time() + token_info.get('expires_in', 3600)
            
            # Save token to cache
            cache_path = os.path.join(BASE_DIR, ".spotify_cache")
            with open(cache_path, 'w') as f:
                json.dump(token_info, f)
            
            # Create Spotipy client with token
            self.sp = spotipy.Spotify(auth=token_info['access_token'])
            
            print("✅ Spotify token refreshed")
            return True
            
        except Exception as e:
            print(f"❌ Token refresh failed: {e}")
            return False
    
    def get_spotify_auth_url(self):
        """Generate Spotify authorization URL"""
        import urllib.parse
        
        params = {
            'client_id': CLIENT_ID,
            'response_type': 'code',
            'redirect_uri': REDIRECT_URI,
            'scope': SCOPE,
            'state': 'noir_player_auth'
        }
        
        return f"https://accounts.spotify.com/authorize?{urllib.parse.urlencode(params)}"
    
    def exchange_code_for_token(self, code):
        """Exchange authorization code for access token"""
        import requests
        import base64
        import time
        
        try:
            # Encode client credentials
            client_creds = f"{CLIENT_ID}:{CLIENT_SECRET}"
            encoded_creds = base64.b64encode(client_creds.encode()).decode()
            
            # Request token
            token_url = "https://accounts.spotify.com/api/token"
            headers = {
                'Authorization': f'Basic {encoded_creds}',
                'Content-Type': 'application/x-www-form-urlencoded'
            }
            
            data = {
                'grant_type': 'authorization_code',
                'code': code,
                'redirect_uri': REDIRECT_URI
            }
            
            response = requests.post(token_url, headers=headers, data=data)
            response.raise_for_status()
            
            token_info = response.json()
            
            # Add expires_at timestamp
            token_info['expires_at'] = time.time() + token_info.get('expires_in', 3600)
            
            # Save token to cache
            cache_path = os.path.join(BASE_DIR, ".spotify_cache")
            with open(cache_path, 'w') as f:
                json.dump(token_info, f)
            
            # Create Spotipy client with token
            self.sp = spotipy.Spotify(auth=token_info['access_token'])
            
            # Verify connection
            user = self.sp.current_user()
            print(f"✅ Spotify authentication successful! Welcome, {user.get('display_name', 'User')}")
            return True
            
        except Exception as e:
            print(f"❌ Token exchange failed: {e}")
            return False
    def get_liked_tracks_page(self, limit=TRACKS_PER_PAGE, offset=0):
        """Get a single page of liked tracks"""
        if not self.sp:
            return []
        
        try:
            results = self.sp.current_user_saved_tracks(limit=limit, offset=offset)
            
            tracks = []
            for item in results["items"]:
                track = item.get("track")
                if not track:
                    continue
                
                album_images = track.get("album", {}).get("images", [])
                thumbnail = None
                if album_images:
                    sorted_images = sorted(album_images, key=lambda x: x.get('height', 0), reverse=True)
                    thumbnail = sorted_images[0]["url"] if sorted_images else None
                
                tracks.append({
                    "title": track["name"],
                    "artist": track["artists"][0]["name"] if track.get("artists") else "Unknown",
                    "duration": track.get("duration_ms", 0) // 1000,
                    "duration_str": f"{track.get('duration_ms', 0) // 60000}:{(track.get('duration_ms', 0) % 60000) // 1000:02d}",
                    "thumbnail": thumbnail,
                    "album": track.get("album", {}).get("name", "Unknown Album"),
                    "id": track.get("id", ""),
                    "popularity": track.get("popularity", 0),
                    "loaded_at": offset + len(tracks)
                })
            
            self.total_tracks = results.get("total", 0)
            self.current_offset = offset
            return tracks
            
        except Exception as e:
            print(f"Error fetching tracks: {e}")
            return []
    
    def get_all_liked_tracks(self, max_tracks=MAX_TRACKS):
        """Get all liked tracks up to max_tracks"""
        if not self.sp:
            return []
        
        try:
            all_tracks = []
            offset = 0
            limit = TRACKS_PER_PAGE
            
            while offset < max_tracks:
                results = self.sp.current_user_saved_tracks(limit=limit, offset=offset)
                if not results or not results.get("items"):
                    break
                
                page_tracks = []
                for item in results["items"]:
                    track = item.get("track")
                    if not track:
                        continue
                    
                    album_images = track.get("album", {}).get("images", [])
                    thumbnail = None
                    if album_images:
                        sorted_images = sorted(album_images, key=lambda x: x.get('height', 0), reverse=True)
                        thumbnail = sorted_images[0]["url"] if sorted_images else None
                    
                    page_tracks.append({
                        "title": track["name"],
                        "artist": track["artists"][0]["name"] if track.get("artists") else "Unknown",
                        "duration": track.get("duration_ms", 0) // 1000,
                        "duration_str": f"{track.get('duration_ms', 0) // 60000}:{(track.get('duration_ms', 0) % 60000) // 1000:02d}",
                        "thumbnail": thumbnail,
                        "album": track.get("album", {}).get("name", "Unknown Album"),
                        "id": track.get("id", ""),
                        "popularity": track.get("popularity", 0),
                        "loaded_at": offset + len(page_tracks)
                    })
                
                all_tracks.extend(page_tracks)
                offset += len(page_tracks)
                
                if len(all_tracks) >= results.get("total", 0) or len(all_tracks) >= max_tracks:
                    break
            
            self.total_tracks = results.get("total", 0) if results else 0
            return all_tracks
            
        except Exception as e:
            print(f"Error fetching all tracks: {e}")
            return []

# ============================================
# MAIN NOIRPLAYER CLASS (COMPLETE)
# ============================================
class NoirPlayer:
    def __init__(self):
        self.spotify = SpotifyClient()
        self.settings = SettingsManager()
        self.player = MediaPlayer()
        self.classifier = MusicClassifier()
        self.playlist_manager = PlaylistManager()
        
        self.tracks = []
        self.downloaded_tracks = []
        self.liked_tracks = []
        self.liked_tracks_file = os.path.join(BASE_DIR, "liked_tracks.json")
        self.playlists = {}
        self.current_playlist = "Downloads"
        self.downloading = False
        self.download_queue = []
        self.window = None
        self.current_playing_index = None
        self.playback_update_interval = None
        
        self.search_results = []
        self.similar_tracks_results = {}
        self.current_search_term = ""
        
        output_dir = self.settings.get_setting("output_dir", OUTPUT_DIR)
        os.makedirs(output_dir, exist_ok=True)
        
        initial_volume = self.settings.get_setting("volume", 0.7)
        self.player.set_volume(initial_volume)
        
        self.scan_downloaded_tracks()
        self.load_liked_tracks()
    
    # ============================================
    # LIKE/UNLIKE SYSTEM
    # ============================================
    
    def load_liked_tracks(self):
        """Load liked tracks from file"""
        try:
            if os.path.exists(self.liked_tracks_file):
                with open(self.liked_tracks_file, 'r') as f:
                    self.liked_tracks = json.load(f)
                print(f"✅ Loaded {len(self.liked_tracks)} liked tracks")
        except Exception as e:
            print(f"Error loading liked tracks: {e}")
            self.liked_tracks = []
    
    def save_liked_tracks(self):
        """Save liked tracks to file"""
        try:
            with open(self.liked_tracks_file, 'w') as f:
                json.dump(self.liked_tracks, f, indent=2)
            return True
        except Exception as e:
            print(f"Error saving liked tracks: {e}")
            return False
    
    def like_track(self, track_data):
        """Like a track (works for Spotify, downloaded, streamed, discovered)"""
        try:
            # Ensure required fields
            if not track_data.get('title') or not track_data.get('artist'):
                return {"success": False, "message": "Track data incomplete"}
            
            # Generate unique ID
            track_id = hashlib.md5(f"{track_data['artist']}_{track_data['title']}".encode()).hexdigest()
            
            # Check if already liked
            for track in self.liked_tracks:
                if track.get('track_id') == track_id:
                    return {"success": False, "message": "Track already liked"}
            
            # Add metadata
            liked_track = {
                "track_id": track_id,
                "title": track_data.get('title', 'Unknown'),
                "artist": track_data.get('artist', 'Unknown'),
                "album": track_data.get('album', 'Unknown Album'),
                "duration": track_data.get('duration', 0),
                "thumbnail": track_data.get('thumbnail'),
                "source": track_data.get('source', 'unknown'),
                "youtube_url": track_data.get('youtube_url'),
                "spotify_id": track_data.get('id'),
                "filepath": track_data.get('filepath'),
                "liked_at": datetime.now().isoformat(),
                "is_liked": True
            }
            
            # Add to liked tracks
            self.liked_tracks.append(liked_track)
            self.save_liked_tracks()
            
            # Update recommendations
            self.classifier.log_play(liked_track)
            
            return {
                "success": True, 
                "message": f"❤️ Liked: {track_data['artist']} - {track_data['title']}",
                "track_id": track_id
            }
            
        except Exception as e:
            print(f"Error liking track: {e}")
            return {"success": False, "message": f"Error: {str(e)}"}
    
    def unlike_track(self, track_id):
        """Unlike a track by track_id"""
        try:
            initial_count = len(self.liked_tracks)
            self.liked_tracks = [t for t in self.liked_tracks if t.get('track_id') != track_id]
            
            if len(self.liked_tracks) < initial_count:
                self.save_liked_tracks()
                return {"success": True, "message": "Track unliked"}
            else:
                return {"success": False, "message": "Track not found in likes"}
                
        except Exception as e:
            print(f"Error unliking track: {e}")
            return {"success": False, "message": f"Error: {str(e)}"}
    
    def is_track_liked(self, artist, title):
        """Check if a track is liked"""
        try:
            track_id = hashlib.md5(f"{artist}_{title}".encode()).hexdigest()
            for track in self.liked_tracks:
                if track.get('track_id') == track_id:
                    return {"success": True, "is_liked": True, "track": track}
            return {"success": True, "is_liked": False}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def get_liked_tracks_list(self):
        """Get all liked tracks"""
        return self.liked_tracks
    
    # ============================================
    # PLAYLIST FUNCTIONS - FIXED
    # ============================================
    
    def create_playlist(self, name, description="", folder_path=None):
        """Create a new playlist - FIXED (only 3 parameters)"""
        try:
            if not name or not name.strip():
                return {"success": False, "message": "Playlist name cannot be empty"}
            
            success = self.playlist_manager.create_playlist(name.strip(), folder_path, description)
            if success:
                return {"success": True, "message": f"Playlist '{name}' created"}
            else:
                return {"success": False, "message": "Playlist already exists"}
        except Exception as e:
            print(f"Error creating playlist: {e}")
            return {"success": False, "message": f"Error: {str(e)}"}
    
    def delete_playlist(self, name):
        """Delete a playlist"""
        try:
            success = self.playlist_manager.delete_playlist(name)
            if success:
                return {"success": True, "message": f"Playlist '{name}' deleted"}
            else:
                return {"success": False, "message": "Cannot delete system playlists"}
        except Exception as e:
            print(f"Error deleting playlist: {e}")
            return {"success": False, "message": f"Error: {str(e)}"}
    
    def get_playlists(self):
        """Get all playlists with full details"""
        try:
            # Ensure Downloads playlist is populated
            downloads_tracks = self.get_downloaded_tracks()
            if "Downloads" in self.playlist_manager.playlists:
                # Convert downloaded tracks to playlist format
                playlist_tracks = []
                for track in downloads_tracks:
                    playlist_tracks.append({
                        "title": track["title"],
                        "artist": track["artist"],
                        "duration": track.get("duration", 0),
                        "duration_str": track.get("duration_str", "0:00"),
                        "thumbnail": track.get("thumbnail"),
                        "filepath": track.get("filepath"),
                        "filename": track.get("filename")
                    })
                
                self.playlist_manager.playlists["Downloads"]["tracks"] = playlist_tracks
                self.playlist_manager.playlists["Downloads"]["last_updated"] = datetime.now().isoformat()
            
            return self.playlist_manager.playlists
        except Exception as e:
            print(f"Error getting playlists: {e}")
            return self.playlist_manager.playlists
        
    def add_track_to_playlist(self, playlist_name, track_data):
        """Add a track to a playlist"""
        try:
            if playlist_name not in self.playlist_manager.playlists:
                return {"success": False, "message": f"Playlist '{playlist_name}' not found"}
            
            # Prepare track data
            track_to_add = {
                "title": track_data.get("title", "Unknown"),
                "artist": track_data.get("artist", "Unknown"),
                "duration": track_data.get("duration", 0),
                "duration_str": track_data.get("duration_str", "0:00"),
                "thumbnail": track_data.get("thumbnail"),
                "album": track_data.get("album", "Unknown Album"),
                "source": track_data.get("source", "unknown"),
                "youtube_url": track_data.get("youtube_url"),
                "spotify_id": track_data.get("id"),
                "filepath": track_data.get("filepath"),
                "added_at": datetime.now().isoformat()
            }
            
            # Add to playlist
            success = self.playlist_manager.add_to_playlist(playlist_name, track_to_add)
            
            if success:
                return {
                    "success": True,
                    "message": f"Added '{track_to_add['title']}' to {playlist_name}",
                    "playlist": playlist_name,
                    "track": track_to_add
                }
            else:
                return {"success": False, "message": "Track already in playlist"}
                
        except Exception as e:
            print(f"Error adding track to playlist: {e}")
            return {"success": False, "message": f"Error: {str(e)}"}
        
    def play_track_from_history(self, history_index):
        """Play a track from play history"""
        try:
            if not self.classifier.play_history:
                return {"success": False, "message": "No play history available"}
            
            if history_index < 0 or history_index >= len(self.classifier.play_history):
                return {"success": False, "message": "Invalid history index"}
            
            history_item = self.classifier.play_history[history_index]
            track = history_item.get('track', {})
            
            if not track:
                return {"success": False, "message": "Track data not found"}
            
            # Check if track has a filepath (downloaded track)
            if track.get('filepath') and os.path.exists(track.get('filepath')):
                # Play the downloaded track
                self.player.stop()
                
                if self.player.load_track(track['filepath']):
                    if self.player.play():
                        self.current_playing_index = None
                        self.log_play_for_recommendations(track)
                        return {
                            "success": True,
                            "message": f"Now playing: {track['artist']} - {track['title']}",
                            "track": track
                        }
                return {"success": False, "message": "Failed to play track"}
            else:
                # Try to stream from YouTube if available
                if track.get('youtube_url'):
                    stream_info = self._get_youtube_streaming_info(
                        track['youtube_url'], 
                        track, 
                        track
                    )
                    if stream_info.get('success'):
                        return {
                            "success": True,
                            "message": f"Streaming: {track['artist']} - {track['title']}",
                            "track": track,
                            "stream_info": stream_info
                        }
                
                return {
                    "success": False, 
                    "message": "Track not available for playback",
                    "track": track
                }
                
        except Exception as e:
            print(f"Error playing track from history: {e}")
            return {"success": False, "message": f"Error: {str(e)}"}
    
    def get_playlist_tracks(self, playlist_name):
        """Get tracks from a playlist"""
        try:
            return self.playlist_manager.get_playlist_tracks(playlist_name)
        except Exception as e:
            print(f"Error getting playlist tracks: {e}")
            return []
    
    def add_to_playlist(self, playlist_name, track):
        """Add track to playlist"""
        try:
            success = self.playlist_manager.add_to_playlist(playlist_name, track)
            if success:
                return {"success": True, "message": f"Added to {playlist_name}"}
            else:
                return {"success": False, "message": "Failed to add to playlist"}
        except Exception as e:
            print(f"Error adding to playlist: {e}")
            return {"success": False, "message": f"Error: {str(e)}"}
    
    def remove_from_playlist(self, playlist_name, track_index):
        """Remove track from playlist"""
        try:
            success = self.playlist_manager.remove_from_playlist(playlist_name, track_index)
            if success:
                return {"success": True, "message": f"Removed from {playlist_name}"}
            else:
                return {"success": False, "message": "Failed to remove from playlist"}
        except Exception as e:
            print(f"Error removing from playlist: {e}")
            return {"success": False, "message": f"Error: {str(e)}"}
    
    # ============================================
    # DISCOVER FUNCTIONS
    # ============================================
    
    def discover_search(self, query):
        """Search for music globally (called from JavaScript)"""
        try:
            results = []
            
            # Search in downloaded tracks
            for track in self.downloaded_tracks:
                if query.lower() in track["title"].lower() or \
                   query.lower() in track["artist"].lower():
                    results.append({
                        "type": "local",
                        "track": track,
                        "source": "Your Library"
                    })
            
            # Search in Spotify tracks
            for idx, track in enumerate(self.tracks):
                if query.lower() in track["title"].lower() or \
                   query.lower() in track["artist"].lower():
                    results.append({
                        "type": "spotify",
                        "track": track,
                        "index": idx,
                        "source": "Spotify"
                    })
            
            # Search YouTube
            yt_results = self.search_youtube_music(query, limit=20)
            results.extend(yt_results)
            
            return {
                "success": True,
                "results": results,
                "count": len(results)
            }
        except Exception as e:
            print(f"Error in discover_search: {e}")
            return {
                "success": False,
                "error": str(e),
                "results": [],
                "count": 0
            }
    
    def search_youtube_music(self, query, limit=10):
        """Search YouTube for music"""
        try:
            ydl_opts = {
                "format": "bestaudio/best",
                "quiet": True,
                "skip_download": True,
                "noplaylist": True,
                "no_warnings": True,
                "extract_flat": True,
                "socket_timeout": 10,
            }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                search_result = ydl.extract_info(f"ytsearch{limit}:{query}", download=False)
                if not search_result or "entries" not in search_result:
                    return []
                
                results = []
                for entry in search_result["entries"]:
                    if not entry:
                        continue
                    
                    duration = entry.get("duration", 0)
                    if isinstance(duration, (int, float)) and 30 < duration < 1800:
                        video_id = entry.get('id', '')
                        thumbnail = f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg" if video_id else None
                        
                        # Extract artist from title (common YouTube format: "Artist - Title")
                        title = entry.get("title", "Unknown")
                        artist = entry.get("uploader", "Unknown")
                        
                        # Try to parse "Artist - Title" format
                        if " - " in title:
                            parts = title.split(" - ", 1)
                            if len(parts) == 2:
                                artist = parts[0].strip()
                                title = parts[1].strip()
                        
                        results.append({
                            "title": title,
                            "artist": artist,
                            "duration": duration,
                            "duration_str": f"{int(duration//60)}:{int(duration%60):02d}",
                            "thumbnail": thumbnail,
                            "youtube_url": entry.get("url"),
                            "video_id": video_id,
                            "view_count": entry.get("view_count"),
                            "uploader": entry.get("uploader", "Unknown"),
                            "description": entry.get("description", "")[:200] + "..." if entry.get("description") else "",
                            "source": "YouTube"
                        })
                
                return results
        except Exception as e:
            print(f"Error searching YouTube: {e}")
            return []
    
    def get_most_played(self):
        """Get user's most played tracks"""
        try:
            # Get play history from classifier
            if self.classifier.play_history:
                # Count plays per track
                track_counts = defaultdict(int)
                track_info = {}
                
                for play in self.classifier.play_history:
                    track_id = play.get('track_id', '')
                    if track_id:
                        track_counts[track_id] += 1
                        track_info[track_id] = play.get('track', {})
                
                # Sort by play count
                sorted_tracks = sorted(track_counts.items(), key=lambda x: x[1], reverse=True)[:10]
                
                # Format results
                results = []
                for track_id, count in sorted_tracks:
                    if track_id in track_info:
                        track = track_info[track_id].copy()
                        track["play_count"] = count
                        results.append(track)
                
                return results
            
            return []
        except Exception as e:
            print(f"Error getting most played: {e}")
            return []
    
    def get_recommendations(self):
        """Get personalized recommendations"""
        try:
            # Combine all tracks: liked, Spotify, and downloaded
            all_tracks = self.liked_tracks + self.tracks + self.downloaded_tracks
            
            # Get recommendations from classifier
            recommendations = self.classifier.recommend_based_on_profile(all_tracks, 6)
            
            return recommendations
        except Exception as e:
            print(f"Error getting recommendations: {e}")
            return []
    
    def get_top_genres(self):
        """Get user's top genres"""
        try:
            return self.classifier.get_top_genres(10)
        except Exception as e:
            print(f"Error getting top genres: {e}")
            return []
    
    def get_genre_tracks(self, genre):
        """Get tracks for a specific genre"""
        try:
            all_tracks = self.tracks + self.downloaded_tracks
            return self.classifier.search_tracks_by_genre(all_tracks, genre)[:10]
        except Exception as e:
            print(f"Error getting genre tracks: {e}")
            return []
    
    def discover_search_music(self, query):
        """Search for music globally"""
        results = []
        
        # Search in downloaded tracks
        for track in self.downloaded_tracks:
            if query.lower() in track["title"].lower() or \
               query.lower() in track["artist"].lower():
                results.append({
                    "type": "local",
                    "track": track,
                    "source": "Your Library"
                })
        
        # Search in Spotify tracks
        for idx, track in enumerate(self.tracks):
            if query.lower() in track["title"].lower() or \
               query.lower() in track["artist"].lower():
                results.append({
                    "type": "spotify",
                    "track": track,
                    "index": idx,
                    "source": "Spotify"
                })
        
        # Search YouTube if needed
        if len(results) < 5:
            yt_results = self.search_youtube_music(query)
            results.extend(yt_results)
        
        return results
    
    def get_discover_recommendations(self, count=6):
        """Get personalized recommendations for Discover section"""
        all_tracks = self.tracks + self.downloaded_tracks
        recommendations = self.classifier.recommend_based_on_profile(all_tracks, count)
        
        if len(recommendations) < count:
            if self.classifier.play_history:
                recent = self.classifier.play_history[-20:]
                track_counts = defaultdict(int)
                for play in recent:
                    track_id = play.get('track_id', '')
                    if track_id:
                        track_counts[track_id] += 1
                
                sorted_tracks = sorted(track_counts.items(), key=lambda x: x[1], reverse=True)
                for track_id, _ in sorted_tracks[:count - len(recommendations)]:
                    for track in all_tracks:
                        if f"{track['artist']}_{track['title']}" == track_id:
                            if track not in recommendations:
                                recommendations.append(track)
                                break
        
        return recommendations
    
    def log_play_for_recommendations(self, track):
        """Log a track play for recommendation engine"""
        self.classifier.log_play(track)
            
    def search_spotify_artists(self, query, limit=20):
        """Search Spotify for artists"""
        try:
            if not self.spotify or not self.spotify.sp:
                return []
        
            results = self.spotify.sp.search(q=query, type='artist', limit=limit)
        
            if not results or 'artists' not in results or 'items' not in results['artists']:
                return []
        
            artists = []
            for item in results['artists']['items']:
                if not item:
                    continue
            
                images = item.get('images', [])
                image_url = images[0]['url'] if images and len(images) > 0 else None
            
                artists.append({
                    'name': item.get('name', 'Unknown'),
                    'id': item.get('id', ''),
                    'image': image_url,
                    'followers': item.get('followers', {}).get('total', 0),
                    'popularity': item.get('popularity', 0),
                    'genres': item.get('genres', []),
                    'uri': item.get('uri', ''),
                    'external_url': item.get('external_urls', {}).get('spotify', '')
                })
        
            return artists
        except Exception as e:
            print(f"Error searching artists: {e}")
            return []

    def get_artist_albums(self, artist_id, limit=20):
        """Get all albums by an artist"""
        try:
            if not self.spotify or not self.spotify.sp:
                return []
        
            results = self.spotify.sp.artist_albums(artist_id, limit=limit, album_type='album,single')
        
            if not results or 'items' not in results:
                return []
        
            albums = []
            for item in results['items']:
                if not item:
                    continue
            
                images = item.get('images', [])
                image_url = images[0]['url'] if images and len(images) > 0 else None
            
                albums.append({
                    'name': item.get('name', 'Unknown Album'),
                    'id': item.get('id', ''),
                    'image': image_url,
                    'release_date': item.get('release_date', ''),
                    'total_tracks': item.get('total_tracks', 0),
                    'album_type': item.get('album_type', 'album'),
                    'uri': item.get('uri', ''),
                    'external_url': item.get('external_urls', {}).get('spotify', '')
                })
        
            return albums
        except Exception as e:
            print(f"Error getting artist albums: {e}")
            return []

    def get_artist_top_tracks(self, artist_id, country='US'):
        """Get artist's top tracks"""
        try:
            if not self.spotify or not self.spotify.sp:
                return []
        
            results = self.spotify.sp.artist_top_tracks(artist_id, country=country)
        
            if not results or 'tracks' not in results:
                return []
        
            tracks = []
            for item in results['tracks']:
                if not item:
                    continue
            
                album_images = item.get('album', {}).get('images', [])
                thumbnail = album_images[0]['url'] if album_images and len(album_images) > 0 else None
            
                duration_ms = item.get('duration_ms', 0)
                duration_seconds = duration_ms // 1000
                duration_str = f"{duration_seconds // 60}:{(duration_seconds % 60):02d}"
            
                tracks.append({
                    'title': item.get('name', 'Unknown'),
                    'artist': item.get('artists', [{}])[0].get('name', 'Unknown'),
                    'album': item.get('album', {}).get('name', 'Unknown Album'),
                    'duration': duration_seconds,
                    'duration_str': duration_str,
                    'thumbnail': thumbnail,
                    'id': item.get('id', ''),
                    'popularity': item.get('popularity', 0),
                    'preview_url': item.get('preview_url'),
                    'spotify_uri': item.get('uri', ''),
                    'external_url': item.get('external_urls', {}).get('spotify', '')
                })
        
            return tracks
        except Exception as e:
            print(f"Error getting artist top tracks: {e}")
            return []

    def get_album_tracks(self, album_id):
        """Get all tracks from an album"""
        try:
            if not self.spotify or not self.spotify.sp:
                return []
        
            results = self.spotify.sp.album_tracks(album_id)
            album_info = self.spotify.sp.album(album_id)
        
            if not results or 'items' not in results:
                return []
        
            album_image = None
            if album_info and 'images' in album_info:
                images = album_info['images']
                album_image = images[0]['url'] if images and len(images) > 0 else None
        
            tracks = []
            for item in results['items']:
                if not item:
                    continue
            
                duration_ms = item.get('duration_ms', 0)
                duration_seconds = duration_ms // 1000
                duration_str = f"{duration_seconds // 60}:{(duration_seconds % 60):02d}"
            
                tracks.append({
                    'title': item.get('name', 'Unknown'),
                    'artist': item.get('artists', [{}])[0].get('name', 'Unknown'),
                    'album': album_info.get('name', 'Unknown Album'),
                    'duration': duration_seconds,
                    'duration_str': duration_str,
                    'thumbnail': album_image,
                    'id': item.get('id', ''),
                    'track_number': item.get('track_number', 0),
                    'preview_url': item.get('preview_url'),
                    'spotify_uri': item.get('uri', ''),
                    'external_url': item.get('external_urls', {}).get('spotify', '')
                })
        
            return tracks
        except Exception as e:
            print(f"Error getting album tracks: {e}")
            return []
    
    # ============================================
    # TRACK MANAGEMENT FUNCTIONS
    # ============================================

    def download_track_from_youtube(self, track_info):
        """Download a track with pre-found YouTube URL"""
        try:
            youtube_url = track_info.get('youtube_url')
            if not youtube_url:
                return {"success": False, "error": "No YouTube URL provided"}
            
            # Use the existing download function but with specific URL
            return self.download_alternative_with_url(
                track_info,
                youtube_url,
                self.settings.settings,
                lambda msg, msg_type: print(f"[{msg_type}] {msg}")
            )
            
        except Exception as e:
            return {"success": False, "error": str(e)}

    def search_spotify_tracks(self, query, limit=20):
        """Search Spotify for tracks"""
        try:
            # Check if Spotify client exists and is initialized
            if not self.spotify or not self.spotify.sp:
                print("Spotify client not initialized, attempting to connect...")
                # Try to initialize Spotify
                if not self.spotify.init_client():
                    print("Failed to initialize Spotify client")
                    return []
            
            print(f"Searching Spotify for: {query}")
            
            # Search Spotify
            results = self.spotify.sp.search(q=query, type='track', limit=limit)
            
            print(f"Spotify search results: {results}")
            
            if not results or 'tracks' not in results or 'items' not in results['tracks']:
                print("No tracks found in Spotify results")
                return []
            
            items = results['tracks']['items']
            print(f"Found {len(items)} tracks on Spotify")
            
            tracks = []
            for item in items:
                if not item:
                    continue
                
                # Get album art
                album_images = item.get('album', {}).get('images', [])
                thumbnail = None
                if album_images:
                    sorted_images = sorted(album_images, key=lambda x: x.get('height', 0), reverse=True)
                    thumbnail = sorted_images[0]['url'] if sorted_images else None
                
                # Get artist name
                artists = item.get('artists', [])
                artist_name = artists[0]['name'] if artists and len(artists) > 0 else 'Unknown'
                
                # Get duration
                duration_ms = item.get('duration_ms', 0)
                duration_seconds = duration_ms // 1000
                duration_str = f"{duration_seconds // 60}:{(duration_seconds % 60):02d}"
                
                track_data = {
                    'title': item.get('name', 'Unknown'),
                    'artist': artist_name,
                    'album': item.get('album', {}).get('name', 'Unknown Album'),
                    'duration': duration_seconds,
                    'duration_str': duration_str,
                    'thumbnail': thumbnail,
                    'id': item.get('id', ''),
                    'popularity': item.get('popularity', 0),
                    'source': 'Spotify',
                    'preview_url': item.get('preview_url'),
                    'spotify_uri': item.get('uri', ''),
                    'external_url': item.get('external_urls', {}).get('spotify', '')
                }
                
                tracks.append(track_data)
                print(f"Added track: {artist_name} - {item.get('name')}")
            
            print(f"Returning {len(tracks)} Spotify tracks")
            return tracks
            
        except Exception as e:
            print(f"Error searching Spotify: {e}")
            import traceback
            traceback.print_exc()
            return []

    def combined_music_search(self, query, limit=30, offset=0):
        """Search both Spotify (tracks + playlists) and YouTube"""
        try:
            results = []
            spotify_tracks = []
            spotify_playlists = []
            youtube_tracks = []
            
            print(f"Combined search for: {query} (limit: {limit}, offset: {offset})")
            
            # Search Spotify tracks
            try:
                print("Searching Spotify tracks...")
                spotify_tracks = self.search_spotify_tracks(query, limit=20)
                print(f"Spotify returned {len(spotify_tracks)} tracks")
                
                for track in spotify_tracks:
                    results.append({
                        'type': 'spotify_track',
                        'track': track,
                        'source': 'Spotify'
                    })
            except Exception as e:
                print(f"Spotify tracks search failed: {e}")
            
            # Search Spotify playlists
            try:
                print("Searching Spotify playlists...")
                spotify_playlists = self.search_spotify_playlists(query, limit=10)
                print(f"Spotify returned {len(spotify_playlists)} playlists")
                
                for playlist in spotify_playlists:
                    results.append({
                        'type': 'spotify_playlist',
                        'playlist': playlist,
                        'source': 'Spotify Playlist'
                    })
            except Exception as e:
                print(f"Spotify playlists search failed: {e}")
            
            # Search YouTube
            try:
                print("Searching YouTube...")
                youtube_tracks = self.search_youtube_music(query, limit=15)
                print(f"YouTube returned {len(youtube_tracks)} tracks")
                
                for track in youtube_tracks:
                    results.append({
                        'type': 'youtube',
                        'track': track,
                        'source': 'YouTube'
                    })
            except Exception as e:
                print(f"YouTube search failed: {e}")
            
            print(f"Total results: {len(results)} (Spotify: {len(spotify_tracks)}, Playlists: {len(spotify_playlists)}, YouTube: {len(youtube_tracks)})")
            
            return {
                'success': True,
                'results': results,
                'count': len(results),
                'spotify_count': len(spotify_tracks),
                'spotify_playlists_count': len(spotify_playlists),
                'youtube_count': len(youtube_tracks),
                'has_more': False  # We'll implement pagination later if needed
            }
            
        except Exception as e:
            print(f"Error in combined search: {e}")
            import traceback
            traceback.print_exc()
            return {
                'success': False,
                'error': str(e),
                'results': [],
                'count': 0,
                'spotify_count': 0,
                'spotify_playlists_count': 0,
                'youtube_count': 0
            }
    
    def scan_downloaded_tracks(self):
        """Scan the download directory for already downloaded tracks"""
        self.downloaded_tracks = []
        output_dir = self.settings.get_setting("output_dir", OUTPUT_DIR)
        
        if os.path.exists(output_dir):
            for file in os.listdir(output_dir):
                if file.endswith(('.mp3', '.m4a', '.webm', '.flac', '.ogg')):
                    if file.endswith(('.jpg', '.jpeg', '.png')):
                        continue
                    
                    filename = os.path.splitext(file)[0]
                    parts = filename.split(' - ', 1)
                    if len(parts) == 2:
                        artist, title = parts
                        
                        audio_file = os.path.join(output_dir, file)
                        
                        cover_data = None
                        embedded_cover_path = get_embedded_cover(audio_file)
                        if embedded_cover_path:
                            cover_data = image_to_base64(embedded_cover_path)
                        
                        if not cover_data:
                            for cover_ext in ['.jpg', '.jpeg', '.png']:
                                cover_file = os.path.join(output_dir, f"{artist} - {title}{cover_ext}")
                                if os.path.exists(cover_file):
                                    cover_data = image_to_base64(cover_file)
                                    break
                        
                        duration = 0
                        try:
                            file_ext = os.path.splitext(audio_file)[1].lower()
                            if file_ext == '.mp3':
                                from mutagen.mp3 import MP3
                                audio = MP3(audio_file)
                                duration = audio.info.length
                            elif file_ext == '.m4a':
                                from mutagen.mp4 import MP4
                                audio = MP4(audio_file)
                                duration = audio.info.length
                        except:
                            pass
                        
                        self.downloaded_tracks.append({
                            "title": title,
                            "artist": artist,
                            "filename": file,
                            "filepath": audio_file,
                            "downloaded_at": os.path.getmtime(audio_file),
                            "thumbnail": cover_data,
                            "duration": duration,
                            "duration_str": format_time(duration)
                        })
    
    def is_track_downloaded(self, track):
        """Check if a track is already downloaded"""
        safe_artist = clean_filename(track["artist"])
        safe_title = clean_filename(track["title"])
        output_dir = self.settings.get_setting("output_dir", OUTPUT_DIR)
        
        for ext in ['.mp3', '.m4a', '.webm', '.flac', '.ogg']:
            filename = f"{safe_artist} - {safe_title}{ext}"
            filepath = os.path.join(output_dir, filename)
            if os.path.exists(filepath):
                return True
        return False
    
    def get_downloaded_tracks(self):
        """Get list of downloaded tracks"""
        self.scan_downloaded_tracks()
        return self.downloaded_tracks
    
    # ============================================
    # SETTINGS FUNCTIONS
    # ============================================
    
    def get_settings(self):
        """Get current settings"""
        return self.settings.settings
    
    def update_settings(self, new_settings):
        """Update application settings"""
        for key, value in new_settings.items():
            if key in self.settings.settings:
                self.settings.settings[key] = value
        
        if "volume" in new_settings:
            self.player.set_volume(new_settings["volume"])
        
        if "output_dir" in new_settings:
            os.makedirs(new_settings["output_dir"], exist_ok=True)
            self.scan_downloaded_tracks()
        
        return self.settings.save_settings()
    
    def get_output_dir(self):
        """Get the output directory path"""
        return self.settings.get_setting("output_dir", OUTPUT_DIR)
    
    # ============================================
    # PLAYBACK FUNCTIONS
    # ============================================
    
    def play_track(self, track_index):
        """Play a downloaded track"""
        try:
            if track_index < 0 or track_index >= len(self.downloaded_tracks):
                return {"success": False, "message": "Invalid track index"}
            
            track = self.downloaded_tracks[track_index]
            
            # Log play for recommendations
            self.log_play_for_recommendations(track)
            
            self.player.stop()
            
            if self.player.load_track(track["filepath"]):
                if self.player.play():
                    self.current_playing_index = track_index
                    return {
                        "success": True,
                        "message": f"Now playing: {track['artist']} - {track['title']}",
                        "track": track
                    }
            
            return {"success": False, "message": "Failed to play track"}
            
        except Exception as e:
            return {"success": False, "message": f"Error: {str(e)}"}
    
    def play_pause(self):
        """Toggle play/pause"""
        try:
            if not self.player.current_track:
                return {"success": False, "message": "No track loaded"}
            
            if self.player.is_playing:
                self.player.pause()
                return {"success": True, "message": "Paused", "is_playing": False}
            elif self.player.is_paused:
                self.player.unpause()
                return {"success": True, "message": "Playing", "is_playing": True}
            else:
                if self.player.play():
                    return {"success": True, "message": "Playing", "is_playing": True}
                else:
                    return {"success": False, "message": "Failed to play"}
            
        except Exception as e:
            return {"success": False, "message": f"Error: {str(e)}"}
    
    def stop_playback(self):
        """Stop playback"""
        try:
            self.player.stop()
            self.current_playing_index = None
            return {"success": True, "message": "Playback stopped"}
        except Exception as e:
            return {"success": False, "message": f"Error: {str(e)}"}
    
    def set_volume(self, volume):
        """Set playback volume"""
        try:
            volume = float(volume)
            if self.player.set_volume(volume):
                self.settings.update_setting("volume", volume)
                return {"success": True, "message": f"Volume set to {int(volume * 100)}%"}
            else:
                return {"success": False, "message": "Failed to set volume"}
        except Exception as e:
            return {"success": False, "message": f"Error: {str(e)}"}
    
    def set_position(self, position):
        """Set playback position"""
        try:
            position = float(position)
            if self.player.set_position(position):
                return {"success": True, "message": f"Position set to {format_time(position)}"}
            else:
                return {"success": False, "message": "Failed to set position"}
        except Exception as e:
            return {"success": False, "message": f"Error: {str(e)}"}
    
    def get_playback_info(self):
        """Get current playback information"""
        try:
            info = self.player.get_playback_info()
            current_track = None
            if self.current_playing_index is not None and self.current_playing_index < len(self.downloaded_tracks):
                current_track = self.downloaded_tracks[self.current_playing_index]
            
            return {
                "success": True,
                "playback_info": info,
                "current_track": current_track
            }
        except Exception as e:
            return {"success": False, "message": f"Error: {str(e)}"}
    
    # ============================================
    # SPOTIFY FUNCTIONS
    # ============================================
    
    def connect_spotify(self):
        """Connect to Spotify"""
        try:
            if self.spotify.init_client():
                if self.spotify.sp:
                    results = self.spotify.sp.current_user_saved_tracks(limit=1, offset=0)
                    total_tracks = results.get("total", 0)
                    return {
                        "success": True, 
                        "message": "Connected to Spotify",
                        "total_tracks": total_tracks
                    }
            return {"success": False, "error": "Failed to connect to Spotify"}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def load_tracks(self, offset=0, load_all=False):
        """Load tracks from Spotify with pagination or all at once"""
        try:
            if not self.spotify.sp:
                success = self.spotify.init_client()
                if not success:
                    return {"tracks": [], "total_tracks": 0}
            
            if load_all:
                tracks = self.spotify.get_all_liked_tracks(max_tracks=MAX_TRACKS)
                if tracks:
                    for track in tracks:
                        track["downloaded"] = self.is_track_downloaded(track)
                    
                    self.tracks = tracks
                    
                    return {
                        "tracks": tracks,
                        "total_tracks": self.spotify.total_tracks,
                        "offset": 0,
                        "has_more": len(tracks) < self.spotify.total_tracks and len(tracks) < MAX_TRACKS
                    }
                else:
                    return {"tracks": [], "total_tracks": 0}
            else:
                tracks = self.spotify.get_liked_tracks_page(limit=TRACKS_PER_PAGE, offset=offset)
                
                for track in tracks:
                    track["downloaded"] = self.is_track_downloaded(track)
                
                if offset == 0:
                    self.tracks = tracks
                else:
                    self.tracks.extend(tracks)
                
                return {
                    "tracks": tracks,
                    "total_tracks": self.spotify.total_tracks,
                    "offset": offset,
                    "has_more": offset + len(tracks) < self.spotify.total_tracks
                }
            
        except Exception as e:
            print(f"Error loading tracks: {e}")
            return {"tracks": [], "total_tracks": 0}
    
    def download_track(self, track_index):
        """Download a single track"""
        try:
            if track_index >= len(self.tracks):
                return {"success": False, "message": "Invalid track index"}
            
            track = self.tracks[track_index]
            
            if self.is_track_downloaded(track):
                return {
                    "success": True, 
                    "message": "Already downloaded",
                    "track": track["title"]
                }
            
            def progress_callback(msg, msg_type):
                print(f"[{msg_type}] {msg}")
            
            success = download_track(track, self.settings.settings, progress_callback)
            
            if success:
                self.tracks[track_index]["downloaded"] = True
                self.scan_downloaded_tracks()
                return {
                    "success": True,
                    "message": "Downloaded successfully",
                    "track": track["title"]
                }
            else:
                return {
                    "success": False,
                    "message": "Download failed",
                    "track": track["title"]
                }
                
        except Exception as e:
            return {"success": False, "message": f"Error: {str(e)}"}
    
    # ============================================
    # SEARCH FUNCTIONS
    # ============================================
    
    def search_tracks(self, query):
        """Search through loaded tracks"""
        if not query or not self.tracks:
            return []
        
        query = query.lower()
        results = []
        
        for idx, track in enumerate(self.tracks):
            track_title = track.get("title", "").lower()
            track_artist = track.get("artist", "").lower()
            track_album = track.get("album", "").lower()
            
            if (query in track_title or 
                query in track_artist or 
                query in track_album):
                results.append({
                    "index": idx,
                    "track": track,
                    "match_type": "title" if query in track_title else 
                                 "artist" if query in track_artist else "album"
                })
        
        self.search_results = results
        return results
    
    # ============================================
    # ALTERNATIVE TRACKS FUNCTIONS
    # ============================================
    
    def find_similar_tracks(self, track_index):
        """Find similar/alternative versions of a track"""
        if track_index >= len(self.tracks):
            return []
        
        track = self.tracks[track_index]
        track_title = track["title"]
        track_artist = track["artist"]
        
        print(f"🔍 Searching for similar tracks for: {track_artist} - {track_title}")
        
        queries = [
            f"{track_artist} {track_title} official audio",
            f"{track_artist} {track_title} lyrics",
            f"{track_artist} {track_title}",
            f"{track_title} {track_artist}",
            f"{track_title}"
        ]
        
        all_results = []
        seen_urls = set()
        
        ydl_opts = {
            "format": "bestaudio/best",
            "quiet": True,
            "skip_download": True,
            "noplaylist": True,
            "no_warnings": True,
            "extract_flat": True,
            "socket_timeout": 10,
        }
        
        for query in queries:
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    search_result = ydl.extract_info(f"ytsearch10:{query}", download=False)
                    if not search_result or "entries" not in search_result:
                        continue
                    
                    for entry in search_result["entries"]:
                        if not entry:
                            continue
                        
                        video_url = entry.get("url")
                        if not video_url or video_url in seen_urls:
                            continue
                        
                        seen_urls.add(video_url)
                        
                        duration = entry.get("duration", 0)
                        if isinstance(duration, (int, float)):
                            duration = float(duration)
                            if 60 < duration < 1800:
                                minutes = int(duration // 60)
                                seconds = int(duration % 60)
                                duration_str = f"{minutes}:{seconds:02d}"
                                
                                all_results.append({
                                    "title": entry.get("title", "Unknown"),
                                    "url": video_url,
                                    "duration": duration,
                                    "duration_str": duration_str,
                                    "uploader": entry.get("uploader", "Unknown"),
                                    "query": query
                                })
                                
            except Exception as e:
                print(f"Error searching for similar tracks: {e}")
                continue
        
        self.similar_tracks_results[track_index] = all_results
        return all_results
    
    def get_streaming_url(self, track_index, alternative_index=None):
        """Get a streaming URL for previewing an alternative track"""
        try:
            # If alternative_index is None, treat track_index as a direct YouTube URL
            if alternative_index is None:
                return self.get_discover_streaming_url(track_index)
            
            if track_index not in self.similar_tracks_results:
                return {"success": False, "message": "No similar tracks found"}
            
            alternatives = self.similar_tracks_results[track_index]
            if alternative_index >= len(alternatives):
                return {"success": False, "message": "Invalid alternative index"}
            
            original_track = self.tracks[track_index]
            alternative = alternatives[alternative_index]
            youtube_url = alternative["url"]
            
            thumbnail = None
            try:
                import re
                video_id_match = re.search(r'(?:youtube\.com\/watch\?v=|youtu\.be\/)([^&?\n]+)', youtube_url)
                if video_id_match:
                    video_id = video_id_match.group(1)
                    thumbnail = f"https://img.youtube.com/vi/{video_id}/maxresdefault.jpg"
                    
                    import requests
                    response = requests.head(thumbnail, timeout=5)
                    if response.status_code != 200:
                        thumbnail = f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg"
            except:
                thumbnail = original_track.get("thumbnail")
            
            ydl_opts = {
                'format': 'bestaudio/best',
                'quiet': True,
                'no_warnings': True,
                'extract_flat': False,
                'socket_timeout': 10,
                'noplaylist': True,
            }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(youtube_url, download=False)
                
                stream_url = None
                if 'url' in info:
                    stream_url = info['url']
                else:
                    formats = info.get('formats', [])
                    for f in formats:
                        if f.get('acodec') and f.get('acodec') != 'none':
                            if 'url' in f:
                                stream_url = f['url']
                                break
                    if not stream_url:
                        stream_url = youtube_url
                
                if not thumbnail and info.get('thumbnail'):
                    thumbnail = info.get('thumbnail')
                
                youtube_title = info.get('title', alternative["title"])
                
                return {
                    "success": True,
                    "stream_url": stream_url,
                    "title": youtube_title,
                    "duration": alternative["duration"],
                    "duration_str": alternative["duration_str"],
                    "thumbnail": thumbnail,
                    "artist": info.get('uploader', original_track["artist"]),
                    "original_title": original_track["title"]
                }
        
        except Exception as e:
            print(f"Error getting streaming URL: {e}")
            if track_index in self.similar_tracks_results and alternative_index < len(self.similar_tracks_results[track_index]):
                alternative = self.similar_tracks_results[track_index][alternative_index]
                original_track = self.tracks[track_index]
                
                return {
                    "success": False,
                    "message": f"Error: {str(e)}",
                    "stream_url": alternative["url"],
                    "title": alternative["title"],
                    "duration": alternative["duration"],
                    "duration_str": alternative["duration_str"],
                    "thumbnail": original_track.get("thumbnail"),
                    "artist": alternative.get("uploader", original_track["artist"])
                }
            return {"success": False, "message": f"Error: {str(e)}"}

    def get_discover_streaming_url(self, youtube_url):
        """Get streaming URL for discovered track - FIXED VERSION"""
        try:
            print(f"Getting streaming URL for: {youtube_url}")
            
            # Create a new yt-dlp instance with proper settings for streaming
            ydl_opts = {
                'format': 'bestaudio/best',
                'quiet': True,
                'no_warnings': True,
                'extract_flat': False,
                'socket_timeout': 15,
                'noplaylist': True,
                'no_color': True,
                'prefer_ffmpeg': False,
                'postprocessors': [],
                # Add these options for better streaming support
                'noprogress': True,
                'skip_download': True,
                'forceurl': True,
                'force_generic_extractor': False,
                'extract_audio': True,
                'audio_format': 'best',
            }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(youtube_url, download=False)
                
                # Try to get a direct audio stream URL
                stream_url = None
                
                # Method 1: Look for audio-only formats
                formats = info.get('formats', [])
                
                # Filter for audio-only formats
                audio_formats = []
                for f in formats:
                    if f.get('acodec') != 'none' and f.get('vcodec') == 'none':
                        # Audio-only format
                        audio_formats.append(f)
                    elif f.get('acodec') != 'none' and f.get('height') is None:
                        # Probably audio-only
                        audio_formats.append(f)
                
                # Sort by quality (bitrate)
                if audio_formats:
                    audio_formats.sort(key=lambda x: x.get('abr', 0) or x.get('tbr', 0), reverse=True)
                    best_format = audio_formats[0]
                    stream_url = best_format.get('url')
                    print(f"Found audio-only format: {best_format.get('format_id')}, bitrate: {best_format.get('abr')}")
                
                # Method 2: Fallback to any format with audio
                if not stream_url:
                    for f in formats:
                        if f.get('acodec') != 'none' and f.get('url'):
                            stream_url = f.get('url')
                            print(f"Using fallback format: {f.get('format_id')}")
                            break
                
                # Method 3: Last resort - use the info dict URL
                if not stream_url and 'url' in info:
                    stream_url = info['url']
                    print("Using info dict URL")
                
                # Method 4: If still no URL, use YouTube URL directly (will need to be handled by browser)
                if not stream_url:
                    stream_url = youtube_url
                    print("No direct stream URL found, using YouTube URL")
                
                print(f"Stream URL found: {stream_url[:100]}...")
                
                # Get video info for display
                title = info.get('title', 'YouTube Video')
                duration = info.get('duration', 0)
                artist = info.get('uploader', 'Unknown Artist')
                thumbnail = info.get('thumbnail', None)
                
                # Try to extract artist/title from YouTube title
                if " - " in title:
                    parts = title.split(" - ", 1)
                    if len(parts) == 2:
                        artist = parts[0].strip()
                        title = parts[1].strip()
                
                # Get video ID for thumbnail
                video_id = None
                if youtube_url:
                    import re
                    video_id_match = re.search(r'(?:youtube\.com\/watch\?v=|youtu\.be\/)([^&?\n]+)', youtube_url)
                    if video_id_match:
                        video_id = video_id_match.group(1)
                        if not thumbnail:
                            thumbnail = f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg"
                
                return {
                    "success": True,
                    "stream_url": stream_url,
                    "title": title,
                    "artist": artist,
                    "duration": duration,
                    "duration_str": self._format_duration(duration),
                    "thumbnail": thumbnail,
                    "video_id": video_id,
                    "is_direct_stream": stream_url != youtube_url
                }
                
        except Exception as e:
            print(f"Error getting streaming URL: {e}")
            import traceback
            traceback.print_exc()
            
            # Fallback: return the YouTube URL and let the browser handle it
            return {
                "success": True,  # Still return success
                "stream_url": youtube_url,
                "title": "YouTube Video",
                "artist": "Unknown Artist",
                "duration": 0,
                "duration_str": "0:00",
                "thumbnail": None,
                "video_id": None,
                "is_direct_stream": False,
                "note": "Using YouTube URL directly"
            }

    def get_popular_artists(self, limit=5):
        """Get popular artists from Spotify - INSTANT with cache"""
        try:
            if not self.spotify or not self.spotify.sp:
                if not self.spotify.init_client():
                    return []
            
            # Hardcoded popular artist IDs for instant loading
            # These are actual Spotify IDs for popular artists
            popular_artist_ids = [
                '3TVXtAsR1Inumwj472S9r4',  # Drake
                '1Xyo4u8uXC1ZmMpatF05PJ',  # The Weeknd
                '06HL4z0CvFAxyc27GXpf02',  # Taylor Swift
                '4q3ewBCX7sLwd24euuV69X',  # Bad Bunny
                '6eUKZXaKkcviH0Ku9w2n3V',  # Ed Sheeran
            ]
            
            artists = []
            
            # Get all artists in one batch (much faster)
            try:
                artist_objects = self.spotify.sp.artists(popular_artist_ids[:limit])
                
                if artist_objects and 'artists' in artist_objects:
                    for item in artist_objects['artists']:
                        if not item:
                            continue
                        
                        images = item.get('images', [])
                        image_url = images[0]['url'] if images and len(images) > 0 else None
                        
                        artists.append({
                            'name': item.get('name', 'Unknown'),
                            'id': item.get('id', ''),
                            'image': image_url,
                            'followers': item.get('followers', {}).get('total', 0),
                            'popularity': item.get('popularity', 0),
                            'genres': item.get('genres', []),
                            'uri': item.get('uri', ''),
                            'external_url': item.get('external_urls', {}).get('spotify', '')
                        })
            except Exception as e:
                print(f"Error fetching artist batch: {e}")
            
            return artists[:limit]
        except Exception as e:
            print(f"Error getting popular artists: {e}")
            return []

    def _get_youtube_streaming_info(self, youtube_url, original_track=None, alternative_track=None):
        """Helper function to get YouTube streaming info"""
        try:
            thumbnail = None
            try:
                import re
                video_id_match = re.search(r'(?:youtube\.com\/watch\?v=|youtu\.be\/)([^&?\n]+)', youtube_url)
                if video_id_match:
                    video_id = video_id_match.group(1)
                    thumbnail = f"https://img.youtube.com/vi/{video_id}/maxresdefault.jpg"
                    
                    import requests
                    response = requests.head(thumbnail, timeout=5)
                    if response.status_code != 200:
                        thumbnail = f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg"
            except:
                if original_track:
                    thumbnail = original_track.get("thumbnail")
            
            ydl_opts = {
                'format': 'bestaudio/best',
                'quiet': True,
                'no_warnings': True,
                'extract_flat': False,
                'socket_timeout': 10,
                'noplaylist': True,
            }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(youtube_url, download=False)
                
                stream_url = None
                if 'url' in info:
                    stream_url = info['url']
                else:
                    formats = info.get('formats', [])
                    for f in formats:
                        if f.get('acodec') and f.get('acodec') != 'none':
                            if 'url' in f:
                                stream_url = f['url']
                                break
                    if not stream_url:
                        stream_url = youtube_url
                
                if not thumbnail and info.get('thumbnail'):
                    thumbnail = info.get('thumbnail')
                
                youtube_title = info.get('title', alternative_track.get("title", "YouTube Video") if alternative_track else "YouTube Video")
                
                return {
                    "success": True,
                    "stream_url": stream_url,
                    "title": youtube_title,
                    "duration": alternative_track.get("duration", info.get('duration', 0)) if alternative_track else info.get('duration', 0),
                    "duration_str": alternative_track.get("duration_str", "0:00") if alternative_track else self._format_duration(info.get('duration', 0)),
                    "thumbnail": thumbnail,
                    "artist": info.get('uploader', original_track.get("artist", "Unknown Artist") if original_track else "Unknown Artist"),
                    "description": info.get('description', '')[:500] if info.get('description') else '',
                    "view_count": info.get('view_count', 0),
                    "upload_date": info.get('upload_date', '')
                }
        
        except Exception as e:
            print(f"Error getting YouTube streaming info: {e}")
            return {
                "success": False,
                "error": str(e),
                "stream_url": youtube_url,
                "title": alternative_track.get("title", "Unknown") if alternative_track else "Unknown",
                "artist": original_track.get("artist", "Unknown") if original_track else "Unknown"
            }

    def _format_duration(self, seconds):
        """Format duration in seconds to MM:SS"""
        if not seconds:
            return "0:00"
        minutes = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{minutes}:{secs:02d}"

    def download_alternative_track(self, track_index, alternative_index):
        """Download an alternative version of a track"""
        if track_index not in self.similar_tracks_results:
            return {"success": False, "message": "No similar tracks found"}
        
        alternatives = self.similar_tracks_results[track_index]
        if alternative_index >= len(alternatives):
            return {"success": False, "message": "Invalid alternative index"}
        
        original_track = self.tracks[track_index]
        alternative = alternatives[alternative_index]
        
        print(f"⬇️ Downloading alternative: {alternative['title']}")
        
        track_info = {
            "title": original_track["title"],
            "artist": original_track["artist"],
            "duration": alternative["duration"],
            "album": original_track.get("album", "Unknown Album"),
            "thumbnail": original_track.get("thumbnail")
        }
        
        def progress_callback(msg, msg_type):
            print(f"[{msg_type}] {msg}")
        
        success = self.download_alternative_with_url(
            track_info, 
            alternative["url"], 
            self.settings.settings, 
            progress_callback
        )
        
        if success:
            return {
                "success": True,
                "message": f"Downloaded alternative: {alternative['title']}",
                "original_track": original_track["title"],
                "alternative_title": alternative["title"]
            }
        else:
            return {
                "success": False,
                "message": f"Failed to download alternative",
                "original_track": original_track["title"]
            }
        
    def search_spotify_playlists(self, query, limit=20):
        """Search Spotify for public playlists"""
        try:
            if not self.spotify or not self.spotify.sp:
                print("Spotify client not initialized")
                return []
            
            print(f"Searching Spotify playlists for: {query}")
            
            # Search for playlists
            results = self.spotify.sp.search(q=query, type='playlist', limit=limit)
            
            if not results or 'playlists' not in results or 'items' not in results['playlists']:
                print("No playlists found")
                return []
            
            items = results['playlists']['items']
            print(f"Found {len(items)} playlists on Spotify")
            
            playlists = []
            for item in items:
                if not item:
                    continue
                
                # Get playlist image
                images = item.get('images', [])
                thumbnail = None
                if images and len(images) > 0:
                    thumbnail = images[0]['url']
                
                # Get owner info
                owner = item.get('owner', {})
                owner_name = owner.get('display_name', 'Unknown')
                
                playlist_data = {
                    'name': item.get('name', 'Unknown Playlist'),
                    'description': item.get('description', ''),
                    'id': item.get('id', ''),
                    'uri': item.get('uri', ''),
                    'thumbnail': thumbnail,
                    'owner': owner_name,
                    'total_tracks': item.get('tracks', {}).get('total', 0),
                    'public': item.get('public', False),
                    'external_url': item.get('external_urls', {}).get('spotify', ''),
                    'source': 'Spotify Playlist'
                }
                
                playlists.append(playlist_data)
                print(f"Added playlist: {item.get('name')} by {owner_name} ({playlist_data['total_tracks']} tracks)")
            
            print(f"Returning {len(playlists)} Spotify playlists")
            return playlists
            
        except Exception as e:
            print(f"Error searching Spotify playlists: {e}")
            import traceback
            traceback.print_exc()
            return []
        
    def get_current_position(self):
        """Get current playback position and duration"""
        try:
            if not self.player.current_track:
                return {
                    "success": False,
                    "position": 0,
                    "duration": 0,
                    "is_playing": False
                }
            
            position = self.player.get_position()
            duration = self.player.duration
            is_playing = self.player.is_playing
            
            return {
                "success": True,
                "position": position,
                "duration": duration,
                "is_playing": is_playing,
                "is_paused": self.player.is_paused
            }
        except Exception as e:
            print(f"Error getting current position: {e}")
            return {
                "success": False,
                "position": 0,
                "duration": 0,
                "is_playing": False,
                "error": str(e)
            }

    def get_playlist_tracks(self, playlist_id, limit=100):
        """Get tracks from a Spotify playlist"""
        try:
            if not self.spotify or not self.spotify.sp:
                print("Spotify client not initialized")
                return []
            
            print(f"Getting tracks from playlist: {playlist_id}")
            
            # Get playlist tracks
            results = self.spotify.sp.playlist_tracks(playlist_id, limit=limit)
            
            if not results or 'items' not in results:
                print("No tracks found in playlist")
                return []
            
            tracks = []
            for item in results['items']:
                if not item or 'track' not in item:
                    continue
                
                track = item['track']
                if not track:
                    continue
                
                # Get album art
                album_images = track.get('album', {}).get('images', [])
                thumbnail = None
                if album_images:
                    sorted_images = sorted(album_images, key=lambda x: x.get('height', 0), reverse=True)
                    thumbnail = sorted_images[0]['url'] if sorted_images else None
                
                # Get artist
                artists = track.get('artists', [])
                artist_name = artists[0]['name'] if artists and len(artists) > 0 else 'Unknown'
                
                # Get duration
                duration_ms = track.get('duration_ms', 0)
                duration_seconds = duration_ms // 1000
                duration_str = f"{duration_seconds // 60}:{(duration_seconds % 60):02d}"
                
                track_data = {
                    'title': track.get('name', 'Unknown'),
                    'artist': artist_name,
                    'album': track.get('album', {}).get('name', 'Unknown Album'),
                    'duration': duration_seconds,
                    'duration_str': duration_str,
                    'thumbnail': thumbnail,
                    'id': track.get('id', ''),
                    'popularity': track.get('popularity', 0),
                    'source': 'Spotify',
                    'preview_url': track.get('preview_url'),
                    'spotify_uri': track.get('uri', ''),
                    'external_url': track.get('external_urls', {}).get('spotify', '')
                }
                
                tracks.append(track_data)
            
            print(f"Returning {len(tracks)} tracks from playlist")
            return tracks
            
        except Exception as e:
            print(f"Error getting playlist tracks: {e}")
            import traceback
            traceback.print_exc()
            return []

    def advanced_spotify_search(self, query, limit=30):
        """Advanced Spotify search - searches tracks AND related content"""
        try:
            if not self.spotify or not self.spotify.sp:
                print("Spotify client not initialized")
                return {'tracks': [], 'playlists': []}
            
            print(f"Advanced Spotify search for: {query}")
            
            # Search for tracks with genre/style
            track_results = self.spotify.sp.search(q=query, type='track', limit=limit)
            
            tracks = []
            if track_results and 'tracks' in track_results and 'items' in track_results['tracks']:
                for item in track_results['tracks']['items']:
                    if not item:
                        continue
                    
                    album_images = item.get('album', {}).get('images', [])
                    thumbnail = None
                    if album_images:
                        sorted_images = sorted(album_images, key=lambda x: x.get('height', 0), reverse=True)
                        thumbnail = sorted_images[0]['url'] if sorted_images else None
                    
                    artists = item.get('artists', [])
                    artist_name = artists[0]['name'] if artists and len(artists) > 0 else 'Unknown'
                    
                    duration_ms = item.get('duration_ms', 0)
                    duration_seconds = duration_ms // 1000
                    duration_str = f"{duration_seconds // 60}:{(duration_seconds % 60):02d}"
                    
                    tracks.append({
                        'title': item.get('name', 'Unknown'),
                        'artist': artist_name,
                        'album': item.get('album', {}).get('name', 'Unknown Album'),
                        'duration': duration_seconds,
                        'duration_str': duration_str,
                        'thumbnail': thumbnail,
                        'id': item.get('id', ''),
                        'popularity': item.get('popularity', 0),
                        'source': 'Spotify',
                        'preview_url': item.get('preview_url'),
                        'spotify_uri': item.get('uri', ''),
                        'external_url': item.get('external_urls', {}).get('spotify', '')
                    })
            
            # Also search for playlists with that style
            playlists = self.search_spotify_playlists(query, limit=10)
            
            print(f"Advanced search found {len(tracks)} tracks and {len(playlists)} playlists")
            
            return {
                'tracks': tracks,
                'playlists': playlists
            }
            
        except Exception as e:
            print(f"Error in advanced Spotify search: {e}")
            import traceback
            traceback.print_exc()
            return {'tracks': [], 'playlists': []}

    def enhanced_combined_search(self, query, limit=30):
        """Enhanced search combining Spotify tracks, playlists, and YouTube"""
        try:
            results = []
            spotify_tracks = []
            spotify_playlists = []
            youtube_tracks = []
            
            print(f"Enhanced combined search for: {query}")
            
            # Advanced Spotify search (tracks + playlists)
            try:
                print("Searching Spotify (tracks + playlists)...")
                spotify_results = self.advanced_spotify_search(query, limit=20)
                
                spotify_tracks = spotify_results.get('tracks', [])
                spotify_playlists = spotify_results.get('playlists', [])
                
                print(f"Spotify returned {len(spotify_tracks)} tracks and {len(spotify_playlists)} playlists")
                
                # Add tracks
                for track in spotify_tracks:
                    results.append({
                        'type': 'spotify_track',
                        'track': track,
                        'source': 'Spotify'
                    })
                
                # Add playlists
                for playlist in spotify_playlists:
                    results.append({
                        'type': 'spotify_playlist',
                        'playlist': playlist,
                        'source': 'Spotify Playlist'
                    })
                    
            except Exception as e:
                print(f"Spotify search failed: {e}")
            
            # Search YouTube
            try:
                print("Searching YouTube...")
                youtube_tracks = self.search_youtube_music(query, limit=10)
                print(f"YouTube returned {len(youtube_tracks)} tracks")
                
                for track in youtube_tracks:
                    results.append({
                        'type': 'youtube',
                        'track': track,
                        'source': 'YouTube'
                    })
            except Exception as e:
                print(f"YouTube search failed: {e}")
            
            print(f"Total results: {len(results)} (Spotify tracks: {len(spotify_tracks)}, Playlists: {len(spotify_playlists)}, YouTube: {len(youtube_tracks)})")
            
            return {
                'success': True,
                'results': results,
                'count': len(results),
                'spotify_tracks_count': len(spotify_tracks),
                'spotify_playlists_count': len(spotify_playlists),
                'youtube_count': len(youtube_tracks)
            }
            
        except Exception as e:
            print(f"Error in enhanced combined search: {e}")
            import traceback
            traceback.print_exc()
            return {
                'success': False,
                'error': str(e),
                'results': [],
                'count': 0
            }

    def download_alternative_with_url(self, track, youtube_url, settings, progress_callback=None):
        """Download track with specific YouTube URL"""
        temp_dir = None
        original_file = None
        
        try:
            temp_dir = tempfile.mkdtemp()
            
            output_dir = settings.get("output_dir", OUTPUT_DIR)
            os.makedirs(output_dir, exist_ok=True)
            
            safe_artist = clean_filename(track["artist"])
            safe_title = clean_filename(track["title"])
            filename = f"{safe_artist} - {safe_title} (Alternative)"
            output_path = os.path.join(output_dir, filename)
            
            thumbnail_path = None
            if track.get("thumbnail"):
                thumbnail_path = download_thumbnail(track["thumbnail"], temp_dir)
            
            if progress_callback:
                progress_callback(f"⬇️ Downloading alternative for: {track['artist']} - {track['title']}", "info")
            
            ydl_opts = {
                'format': 'bestaudio/best',
                'outtmpl': os.path.join(temp_dir, 'audio.%(ext)s'),
                'quiet': True,
                'no_warnings': False,
                'writethumbnail': False,
            }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(youtube_url, download=True)
                downloaded_file = ydl.prepare_filename(info)
            
            original_file = downloaded_file
            print(f"Downloaded alternative audio to: {original_file}")
            
            output_ext = ".mp3" if settings["download_as_mp3"] else os.path.splitext(original_file)[1]
            final_output = output_path + output_ext
            
            track_info = {
                "title": track["title"],
                "artist": track["artist"],
                "album": track.get("album", "Unknown Album")
            }
            
            if progress_callback:
                progress_callback(f"🔄 Processing alternative: {track['artist']} - {track['title']}", "info")
            
            success = convert_with_ffmpeg(
                original_file, 
                final_output, 
                settings, 
                thumbnail_path
            )
            
            if not success:
                if progress_callback:
                    progress_callback(f"⚠️ FFmpeg failed, using original file", "warning")
                import shutil
                shutil.copy2(original_file, final_output)
            
            if settings["save_cover_separately"] and thumbnail_path:
                save_cover_separately(thumbnail_path, output_dir, track["artist"], track["title"])
            
            if progress_callback:
                status_msg = f"✅ Downloaded alternative: {track['artist']} - {track['title']}"
                if settings["download_as_mp3"]:
                    status_msg += " [MP3]"
                if settings["embed_thumbnail"] and thumbnail_path:
                    status_msg += " [Cover embedded]"
                if settings["save_cover_separately"] and thumbnail_path:
                    status_msg += " [Cover saved separately]"
                progress_callback(status_msg, "success")
            
            return True
            
        except Exception as e:
            error_msg = str(e)
            if progress_callback:
                progress_callback(f"❌ Failed alternative: {track['artist']} - {track['title']} ({error_msg[:50]})", "error")
            print(f"Download error for alternative: {e}")
            return False
        finally:
            if temp_dir and os.path.exists(temp_dir):
                try:
                    import shutil
                    shutil.rmtree(temp_dir)
                except:
                    pass

    def cleanup_preview_audio(self):
        """Clean up any preview audio resources"""
        try:
            if hasattr(self, 'preview_audio_temp_files'):
                import shutil
                for temp_file in self.preview_audio_temp_files:
                    if os.path.exists(temp_file):
                        if os.path.isdir(temp_file):
                            shutil.rmtree(temp_file, ignore_errors=True)
                        else:
                            os.remove(temp_file)
                self.preview_audio_temp_files = []
        except Exception as e:
            print(f"Error cleaning preview audio: {e}")

    # ============================================
    # UTILITY FUNCTIONS
    # ============================================

    def check_ffmpeg(self):
        """Check if ffmpeg is available"""
        try:
            ffmpeg = get_ffmpeg_path()
            result = subprocess.run([ffmpeg, '-version'], capture_output=True, check=False)
            return result.returncode == 0
        except:
            return False

    # ============================================
    # APPLICATION START
    # ============================================

    def start(self):
        """Start the application"""
        print("🚀 Starting NOIR Music Discovery & Player...")
        print("=" * 50)
        print(f"📁 Base directory: {BASE_DIR}")
        print(f"📁 Downloads will be saved to: {self.settings.get_setting('output_dir', OUTPUT_DIR)}")
        print("🔊 Default volume:", int(self.settings.get_setting("volume", 0.7) * 100), "%")
        print("⚙️  Current settings:")
        print(f"   • Download as MP3: {self.settings.get_setting('download_as_mp3', True)}")
        print(f"   • Embed thumbnail: {self.settings.get_setting('embed_thumbnail', True)}")
        print(f"   • Save cover separately: {self.settings.get_setting('save_cover_separately', False)}")
        print(f"   • MP3 quality: {self.settings.get_setting('mp3_quality', '2')}")
        print("=" * 50)
        
        has_ffmpeg = self.check_ffmpeg()
        if not has_ffmpeg:
            print("⚠️ FFmpeg not found. Some features will be disabled:")
            print("   • MP3 conversion")
            print("   • Thumbnail embedding")
            print("   Install FFmpeg from: https://ffmpeg.org/download.html")
            print("=" * 50)
        else:
            print("✅ FFmpeg found: All features available")
            print("=" * 50)
        
        try:
            import pygame
            print("✅ Pygame found: Media player available")
            print("=" * 50)
        except ImportError:
            print("⚠️ Pygame not found. Media player will not work.")
            print("   Install with: pip install pygame")
            print("=" * 50)
        
        # Load HTML from C:\Musicc\index.html
        html_path = os.path.join(BASE_DIR, "index.html")
        try:
            with open(html_path, "r", encoding="utf-8") as f:
                html_content = f.read()
            print(f"✅ Loaded HTML from {html_path}")
        except FileNotFoundError:
            print(f"❌ HTML file not found at {html_path}. Creating default interface...")
            html_content = """
            <!DOCTYPE html>
            <html>
            <head>
                <title>NOIR Music Player</title>
                <style>
                    body { background: #0a0a0a; color: white; font-family: Arial; padding: 20px; }
                </style>
            </head>
            <body>
                <h1>NOIR Music Discovery & Player</h1>
                <p>HTML file not found. Please ensure 'index.html' exists in C:\\Musicc.</p>
            </body>
            </html>
            """
        
        self.window = webview.create_window(
            'NOIR | Music Discovery & Player',
            html=html_content,
            width=1400,
            height=950,
            resizable=True,
            fullscreen=False,
            # Add this to block Dev Tools on Edge/Chromium backend
            # Note: Some pywebview versions might require specific configuration
        )
        
        # Expose all functions to JavaScript
        self.window.expose(
            # Core functions
            self.connect_spotify,
            self.load_tracks,
            self.download_track,
            self.get_downloaded_tracks,
            self.check_ffmpeg,
            self.get_settings,
            self.update_settings,
            self.get_output_dir,
            
            # Player functions
            self.play_track,
            self.play_pause,
            self.stop_playback,
            self.set_volume,
            self.set_position,
            self.get_playback_info,
            self.add_track_to_playlist,
            self.get_current_position,

            # Artist browser functions
            self.search_spotify_artists,
            self.get_artist_albums,
            self.get_artist_top_tracks,
            self.get_album_tracks,
            self.get_popular_artists,

            self.discover_search,
            self.get_most_played,
            self.get_recommendations,
            self.get_top_genres,
            self.get_genre_tracks,
            
            # Search and discovery
            self.search_tracks,
            self.find_similar_tracks,
            self.download_alternative_track,
            self.get_streaming_url,
            
            # Discover section functions
            self.discover_search_music,
            self.get_discover_recommendations,
            self.get_discover_streaming_url,
            self.get_top_genres,
            self.get_genre_tracks,
            
            # Playlist functions
            self.create_playlist,
            self.delete_playlist,
            self.get_playlists,
            self.get_playlist_tracks,
            self.add_to_playlist,
            self.remove_from_playlist,
            self.search_youtube_music,
            self.search_spotify_playlists,
            self.get_playlist_tracks,
            self.advanced_spotify_search,
            self.enhanced_combined_search,

            # In the self.window.expose() section, add:
            self.search_spotify_tracks,
            self.combined_music_search,
            self.download_track_from_youtube,
            
            # Like/Unlike functions
            self.like_track,
            self.unlike_track,
            self.is_track_liked,
            self.get_liked_tracks_list
        )
        
        # START THE WINDOW
        # Changed debug=True to debug=False to disable Inspect Element and F12
        webview.start(debug=False)

# ============================================
# MAIN ENTRY POINT
# ============================================
if __name__ == "__main__":
    # Check dependencies
    try:
        import webview
    except ImportError:
        print("❌ Missing dependency: pywebview")
        print("   Install with: pip install pywebview")
        sys.exit(1)
    
    try:
        import spotipy
    except ImportError:
        print("❌ Missing dependency: spotipy")
        print("   Install with: pip install spotipy")
        sys.exit(1)
    
    try:
        import yt_dlp
    except ImportError:
        print("❌ Missing dependency: yt-dlp")
        print("   Install with: pip install yt-dlp")
        sys.exit(1)
    
    try:
        import imageio_ffmpeg
    except ImportError:
        print("❌ Missing dependency: imageio-ffmpeg")
        print("   Install with: pip install imageio-ffmpeg")
        sys.exit(1)
    
    try:
        import pygame
    except ImportError:
        print("⚠️ Missing dependency: pygame")
        print("   Media player will not work without pygame")
        print("   Install with: pip install pygame")
        print("=" * 50)
    
    # Optional dependencies
    try:
        from sklearn.metrics.pairwise import cosine_similarity
    except ImportError:
        print("⚠️ Missing dependency: scikit-learn")
        print("   Recommendation engine will be limited")
        print("   Install with: pip install scikit-learn")
        print("=" * 50)
    
    # Create and start the application
    app = NoirPlayer()
    app.start()

