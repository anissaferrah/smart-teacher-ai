"""
Audio Compression Module
Compresse l'audio en Opus (réduction 80% d'espace)
"""

import subprocess
import os
from typing import Tuple, Optional
from pathlib import Path
import logging


class AudioCompression:
    """Compression audio en format Opus"""
    
    def __init__(self, bitrate_kbps: int = 16):
        """
        Initialise le compresseur
        
        Args:
            bitrate_kbps: Bitrate en kbps (16 = qualité bonne + petit fichier)
        """
        self.bitrate_kbps = bitrate_kbps
        self.logger = logging.getLogger(__name__)
        self._check_ffmpeg()
    
    def _check_ffmpeg(self) -> bool:
        """Vérifie que ffmpeg est installé"""
        try:
            subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True)
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            self.logger.warning("ffmpeg non trouvé. Compression audio désactivée.")
            return False
    
    def compress_wav_to_opus(self, input_path: str, output_path: str = None) -> Tuple[bool, str]:
        """
        Compresse un WAV en Opus
        
        Args:
            input_path: Chemin du fichier WAV
            output_path: Chemin de sortie (défaut: input.opus)
            
        Returns:
            Tuple: (succès, chemin_sortie)
        """
        try:
            if output_path is None:
                output_path = str(Path(input_path).with_suffix('.opus'))
            
            # Commande ffmpeg
            cmd = [
                'ffmpeg',
                '-i', input_path,
                '-c:a', 'libopus',
                '-b:a', f'{self.bitrate_kbps}k',
                '-y',  # Overwrite output file
                output_path
            ]
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60
            )
            
            if result.returncode == 0 and os.path.exists(output_path):
                return True, output_path
            else:
                self.logger.error(f"Compression échouée: {result.stderr}")
                return False, ""
        
        except Exception as e:
            self.logger.error(f"Erreur lors de la compression: {str(e)}")
            return False, ""
    
    def compress_wav_to_mp3(self, input_path: str, output_path: str = None, bitrate: int = 64) -> Tuple[bool, str]:
        """
        Compresse un WAV en MP3 (alternative à Opus)
        
        Args:
            input_path: Chemin du fichier WAV
            output_path: Chemin de sortie (défaut: input.mp3)
            bitrate: Bitrate en kbps
            
        Returns:
            Tuple: (succès, chemin_sortie)
        """
        try:
            if output_path is None:
                output_path = str(Path(input_path).with_suffix('.mp3'))
            
            cmd = [
                'ffmpeg',
                '-i', input_path,
                '-codec:a', 'libmp3lame',
                '-b:a', f'{bitrate}k',
                '-y',
                output_path
            ]
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60
            )
            
            if result.returncode == 0 and os.path.exists(output_path):
                return True, output_path
            else:
                self.logger.error(f"Compression MP3 échouée: {result.stderr}")
                return False, ""
        
        except Exception as e:
            self.logger.error(f"Erreur lors de la compression MP3: {str(e)}")
            return False, ""
    
    def get_compression_ratio(self, input_path: str, output_path: str) -> float:
        """
        Calcule le ratio de compression
        
        Args:
            input_path: Chemin du fichier original
            output_path: Chemin du fichier compressé
            
        Returns:
            float: Ratio (original_size / compressed_size)
        """
        try:
            input_size = os.path.getsize(input_path)
            output_size = os.path.getsize(output_path)
            
            if output_size == 0:
                return 0.0
            
            return input_size / output_size
        except Exception:
            return 0.0
    
    def batch_compress_directory(self, input_dir: str, output_dir: str, format: str = 'opus') -> int:
        """
        Compresse tous les fichiers WAV d'un répertoire
        
        Args:
            input_dir: Répertoire source
            output_dir: Répertoire de destination
            format: Format de sortie ('opus' ou 'mp3')
            
        Returns:
            int: Nombre de fichiers compressés
        """
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        
        compressed_count = 0
        input_path = Path(input_dir)
        
        for wav_file in input_path.glob('*.wav'):
            output_file = Path(output_dir) / wav_file.with_suffix(f'.{format}').name
            
            if format == 'opus':
                success, _ = self.compress_wav_to_opus(str(wav_file), str(output_file))
            else:
                success, _ = self.compress_wav_to_mp3(str(wav_file), str(output_file))
            
            if success:
                compressed_count += 1
                self.logger.info(f"Compressé: {wav_file.name}")
        
        return compressed_count
