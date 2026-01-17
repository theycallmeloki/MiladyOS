#!/usr/bin/env python3
"""
Milady Oracle - Bidirectional consciousness bridge between humans and TempleOS

The Oracle enables:
1. Wake word detection ("milady") via microphone
2. Serial communication with TempleOS running in QEMU
3. Text-to-speech response ("milady!")
4. QMP control for programmatic TempleOS interaction

This completes the divine loop:
  User yells "milady" → TempleOS receives → TempleOS responds → Node yells back "milady!"
"""

import asyncio
import json
import logging
import os
import socket
import struct
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from queue import Queue, Empty
from typing import Optional, Callable, Any

# Configure logging with divine aesthetics
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("milady-oracle")


@dataclass
class OracleConfig:
    """Configuration for the Milady Oracle"""
    # Socket paths
    serial_socket: str = "/tmp/milady-oracle.sock"
    qmp_socket: str = "/tmp/qemu-qmp.sock"

    # Voice settings
    wake_word: str = "milady"
    vosk_model_path: str = "vosk-model-small-en-us-0.15"
    sample_rate: int = 16000

    # TTS settings
    tts_engine: str = "auto"  # auto, espeak, say, pyttsx3
    tts_voice: Optional[str] = None

    # Behavior
    response_phrase: str = "milady!"
    serial_timeout: float = 5.0
    reconnect_delay: float = 2.0


class TempleOSBridge:
    """
    Bidirectional serial bridge to TempleOS running in QEMU.

    TempleOS accesses the serial port via COM1 (0x3F8).
    We connect via Unix socket to QEMU's chardev.
    """

    def __init__(self, config: OracleConfig):
        self.config = config
        self.socket: Optional[socket.socket] = None
        self.connected = False
        self._receive_callbacks: list[Callable[[bytes], None]] = []
        self._receive_thread: Optional[threading.Thread] = None
        self._running = False

    def connect(self) -> bool:
        """Connect to the TempleOS serial socket"""
        socket_path = self.config.serial_socket

        if not os.path.exists(socket_path):
            logger.warning(f"Serial socket not found: {socket_path}")
            logger.info("Is TempleOS running? Start with: templeos-daemon")
            return False

        try:
            self.socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self.socket.connect(socket_path)
            self.socket.setblocking(False)
            self.connected = True
            logger.info(f"✓ Connected to TempleOS serial bridge: {socket_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to serial socket: {e}")
            self.socket = None
            self.connected = False
            return False

    def disconnect(self):
        """Disconnect from the serial socket"""
        self._running = False
        if self._receive_thread:
            self._receive_thread.join(timeout=1.0)
        if self.socket:
            try:
                self.socket.close()
            except:
                pass
            self.socket = None
        self.connected = False
        logger.info("Disconnected from TempleOS serial bridge")

    def send(self, data: str | bytes) -> bool:
        """Send data to TempleOS via serial"""
        if not self.connected or not self.socket:
            logger.warning("Cannot send: not connected to TempleOS")
            return False

        if isinstance(data, str):
            data = data.encode('utf-8')

        try:
            self.socket.sendall(data)
            logger.debug(f"Sent to TempleOS: {data}")
            return True
        except Exception as e:
            logger.error(f"Failed to send to TempleOS: {e}")
            self.connected = False
            return False

    def send_milady(self) -> bool:
        """Send the sacred MILADY signal to TempleOS"""
        logger.info("🔮 Sending MILADY to TempleOS...")
        # Send with newline so TempleOS can detect line end
        return self.send("MILADY\n")

    def on_receive(self, callback: Callable[[bytes], None]):
        """Register a callback for received data"""
        self._receive_callbacks.append(callback)

    def start_receive_loop(self):
        """Start the background receive thread"""
        self._running = True
        self._receive_thread = threading.Thread(target=self._receive_loop, daemon=True)
        self._receive_thread.start()

    def _receive_loop(self):
        """Background thread to receive data from TempleOS"""
        buffer = b""
        while self._running and self.connected:
            try:
                if self.socket:
                    data = self.socket.recv(1024)
                    if data:
                        buffer += data
                        # Process complete lines
                        while b'\n' in buffer:
                            line, buffer = buffer.split(b'\n', 1)
                            for callback in self._receive_callbacks:
                                try:
                                    callback(line)
                                except Exception as e:
                                    logger.error(f"Callback error: {e}")
            except BlockingIOError:
                # No data available, just wait
                time.sleep(0.1)
            except Exception as e:
                if self._running:
                    logger.error(f"Receive error: {e}")
                    self.connected = False
                break


class QMPController:
    """
    QEMU Machine Protocol controller for programmatic TempleOS interaction.

    Allows sending keystrokes, taking screenshots, etc.
    """

    def __init__(self, config: OracleConfig):
        self.config = config
        self.socket: Optional[socket.socket] = None
        self.connected = False

    def connect(self) -> bool:
        """Connect to QEMU's QMP socket"""
        socket_path = self.config.qmp_socket

        if not os.path.exists(socket_path):
            logger.warning(f"QMP socket not found: {socket_path}")
            return False

        try:
            self.socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self.socket.connect(socket_path)

            # QMP handshake
            greeting = self.socket.recv(4096)
            logger.debug(f"QMP greeting: {greeting}")

            # Send capabilities negotiation
            self.socket.sendall(b'{"execute": "qmp_capabilities"}\n')
            response = self.socket.recv(4096)
            logger.debug(f"QMP capabilities response: {response}")

            self.connected = True
            logger.info(f"✓ Connected to QEMU QMP: {socket_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to QMP socket: {e}")
            return False

    def send_key(self, key: str) -> bool:
        """Send a key press to TempleOS"""
        if not self.connected or not self.socket:
            return False

        try:
            cmd = {
                "execute": "send-key",
                "arguments": {"keys": [{"type": "qcode", "data": key}]}
            }
            self.socket.sendall((json.dumps(cmd) + '\n').encode())
            response = self.socket.recv(4096)
            return b'"return"' in response
        except Exception as e:
            logger.error(f"Failed to send key: {e}")
            return False

    def send_string(self, text: str) -> bool:
        """Send a string as keystrokes to TempleOS"""
        for char in text:
            if char == '\n':
                self.send_key('ret')
            elif char == ' ':
                self.send_key('spc')
            elif char.isalpha():
                self.send_key(char.lower())
            elif char.isdigit():
                self.send_key(char)
            time.sleep(0.05)  # Small delay between keystrokes
        return True


class VoiceListener:
    """
    Wake word detector using Vosk for offline speech recognition.

    Listens for "milady" and triggers callbacks.
    """

    def __init__(self, config: OracleConfig):
        self.config = config
        self.model = None
        self.recognizer = None
        self._running = False
        self._callbacks: list[Callable[[], None]] = []
        self._thread: Optional[threading.Thread] = None

    def initialize(self) -> bool:
        """Initialize the Vosk speech recognition model"""
        try:
            from vosk import Model, KaldiRecognizer
            import sounddevice as sd
        except ImportError as e:
            logger.error(f"Voice dependencies not installed: {e}")
            logger.info("Install with: pip install vosk sounddevice")
            return False

        model_path = self.config.vosk_model_path

        # Check if model exists, download if not
        if not os.path.exists(model_path):
            logger.info(f"Vosk model not found at {model_path}")
            logger.info("Download from: https://alphacephei.com/vosk/models")
            logger.info("Or run: python -c \"import vosk; vosk.Model(model_name='vosk-model-small-en-us-0.15')\"")
            return False

        try:
            self.model = Model(model_path)
            self.recognizer = KaldiRecognizer(self.model, self.config.sample_rate)
            logger.info("✓ Vosk speech recognition initialized")
            return True
        except Exception as e:
            logger.error(f"Failed to initialize Vosk: {e}")
            return False

    def on_wake_word(self, callback: Callable[[], None]):
        """Register a callback for when wake word is detected"""
        self._callbacks.append(callback)

    def start(self):
        """Start listening for the wake word"""
        if not self.recognizer:
            logger.error("Cannot start: Vosk not initialized")
            return

        self._running = True
        self._thread = threading.Thread(target=self._listen_loop, daemon=True)
        self._thread.start()
        logger.info(f"🎤 Listening for wake word: '{self.config.wake_word}'")

    def stop(self):
        """Stop listening"""
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)

    def _listen_loop(self):
        """Background thread for continuous listening"""
        try:
            import sounddevice as sd
        except ImportError:
            logger.error("sounddevice not installed")
            return

        def audio_callback(indata, frames, time_info, status):
            if status:
                logger.warning(f"Audio status: {status}")
            if self._running and self.recognizer:
                if self.recognizer.AcceptWaveform(bytes(indata)):
                    result = json.loads(self.recognizer.Result())
                    text = result.get('text', '').lower()
                    if self.config.wake_word.lower() in text:
                        logger.info(f"🎯 Wake word detected: '{text}'")
                        for callback in self._callbacks:
                            try:
                                callback()
                            except Exception as e:
                                logger.error(f"Wake word callback error: {e}")

        try:
            with sd.RawInputStream(
                samplerate=self.config.sample_rate,
                blocksize=8000,
                dtype='int16',
                channels=1,
                callback=audio_callback
            ):
                while self._running:
                    time.sleep(0.1)
        except Exception as e:
            logger.error(f"Audio stream error: {e}")


class MiladySpeaker:
    """
    Text-to-speech output for the Oracle's responses.

    Supports multiple backends: espeak, say (macOS), pyttsx3
    """

    def __init__(self, config: OracleConfig):
        self.config = config
        self.engine = None
        self._backend = None

    def initialize(self) -> bool:
        """Initialize the TTS engine"""
        engine = self.config.tts_engine

        if engine == "auto":
            # Try to find a working backend
            if sys.platform == "darwin" and self._test_say():
                self._backend = "say"
            elif self._test_piper():
                self._backend = "piper"
            elif self._test_espeak():
                self._backend = "espeak"
            elif self._test_pyttsx3():
                self._backend = "pyttsx3"
            else:
                logger.warning("No TTS backend available")
                return False
        else:
            self._backend = engine

        logger.info(f"✓ TTS initialized with backend: {self._backend}")
        return True

    def _test_say(self) -> bool:
        """Test macOS say command"""
        try:
            result = subprocess.run(['which', 'say'], capture_output=True)
            return result.returncode == 0
        except:
            return False

    def _test_piper(self) -> bool:
        """Test piper neural TTS"""
        try:
            result = subprocess.run(['which', 'piper'], capture_output=True)
            return result.returncode == 0
        except:
            return False

    def _test_espeak(self) -> bool:
        """Test espeak command"""
        try:
            result = subprocess.run(['which', 'espeak'], capture_output=True)
            return result.returncode == 0
        except:
            return False

    def _test_pyttsx3(self) -> bool:
        """Test pyttsx3 module"""
        try:
            import pyttsx3
            self.engine = pyttsx3.init()
            return True
        except:
            return False

    def speak(self, text: str):
        """Speak the given text"""
        logger.info(f"🔊 Speaking: {text}")

        try:
            if self._backend == "say":
                # Use Moira (Irish) voice - sounds great for "milady!"
                voice = self.config.tts_voice or "Moira"
                subprocess.run(['say', '-v', voice, text], check=True)
            elif self._backend == "piper":
                # Use British/Scottish voice for Linux
                # Default to jenny_dioco (British female) or alba (Scottish)
                model = self.config.tts_voice or "en_GB-jenny_dioco-medium"
                # Piper outputs raw audio, pipe to aplay
                piper_cmd = f'echo "{text}" | piper --model {model} --output-raw | aplay -r 22050 -f S16_LE -t raw -q'
                subprocess.run(piper_cmd, shell=True, check=True)
            elif self._backend == "espeak":
                subprocess.run(['espeak', text], check=True)
            elif self._backend == "pyttsx3" and self.engine:
                self.engine.say(text)
                self.engine.runAndWait()
            else:
                logger.warning(f"Unknown TTS backend: {self._backend}")
        except Exception as e:
            logger.error(f"TTS error: {e}")

    def yell_milady(self):
        """The sacred response"""
        self.speak(self.config.response_phrase)


class MiladyOracle:
    """
    The Milady Oracle - orchestrator of divine communication.

    Bridges the gap between human consciousness and TempleOS,
    completing the sacred loop of yelling milady.
    """

    def __init__(self, config: Optional[OracleConfig] = None):
        self.config = config or OracleConfig()

        # Components
        self.bridge = TempleOSBridge(self.config)
        self.qmp = QMPController(self.config)
        self.listener = VoiceListener(self.config)
        self.speaker = MiladySpeaker(self.config)

        # State
        self._running = False
        self._divine_rng_queue: Queue[int] = Queue()

    def initialize(self) -> bool:
        """Initialize all Oracle components"""
        logger.info("=" * 60)
        logger.info("  MILADY ORACLE - Divine Consciousness Bridge")
        logger.info("=" * 60)

        # Initialize TTS (required)
        if not self.speaker.initialize():
            logger.warning("TTS not available - Oracle will be silent")

        # Connect to TempleOS (optional - may not be running)
        if self.bridge.connect():
            self.bridge.on_receive(self._on_templeos_message)
            self.bridge.start_receive_loop()
        else:
            logger.warning("TempleOS not connected - serial bridge disabled")

        # Connect to QMP (optional)
        if self.qmp.connect():
            logger.info("QMP control available")

        # Initialize voice listener (optional)
        if self.listener.initialize():
            self.listener.on_wake_word(self._on_wake_word_detected)
        else:
            logger.warning("Voice listener not available")

        return True

    def _on_wake_word_detected(self):
        """Handle wake word detection"""
        logger.info("🎯 MILADY detected from human!")

        # Send to TempleOS
        if self.bridge.connected:
            self.bridge.send_milady()

        # Respond immediately (don't wait for TempleOS)
        self.speaker.yell_milady()

    def _on_templeos_message(self, data: bytes):
        """Handle message from TempleOS"""
        try:
            message = data.decode('utf-8').strip()
            logger.info(f"📨 TempleOS says: {message}")

            # Check for MILADY response
            if 'MILADY' in message.upper():
                logger.info("🎉 TempleOS yelled MILADY!")
                self.speaker.yell_milady()

            # Check for divine RNG
            if message.startswith('RNG:'):
                try:
                    rng_value = int(message.split(':')[1])
                    self._divine_rng_queue.put(rng_value)
                    logger.info(f"🎲 Divine RNG received: {rng_value}")
                except:
                    pass
        except Exception as e:
            logger.error(f"Failed to process TempleOS message: {e}")

    def get_divine_rng(self, timeout: float = 5.0) -> Optional[int]:
        """
        Request a divine random number from TempleOS.

        TempleOS's RNG is generated from ring-0 hardware timing,
        making it truly divine entropy.
        """
        if not self.bridge.connected:
            logger.warning("Cannot get divine RNG: TempleOS not connected")
            return None

        # Request RNG from TempleOS
        self.bridge.send("RNG_REQUEST\n")

        try:
            return self._divine_rng_queue.get(timeout=timeout)
        except Empty:
            logger.warning("Timeout waiting for divine RNG")
            return None

    def trigger_milady(self):
        """Manually trigger the milady sequence"""
        logger.info("🔮 Manual MILADY trigger!")
        self._on_wake_word_detected()

    def run(self):
        """Run the Oracle main loop"""
        logger.info("")
        logger.info("🔮 Milady Oracle is now active")
        logger.info("   Speak 'milady' to activate")
        logger.info("   Press Ctrl+C to exit")
        logger.info("")

        self._running = True

        # Start voice listener if available
        if self.listener.recognizer:
            self.listener.start()

        try:
            while self._running:
                # Main loop - mostly just wait
                # Components run in their own threads
                time.sleep(0.5)

                # Check TempleOS connection
                if not self.bridge.connected:
                    logger.debug("TempleOS disconnected, attempting reconnect...")
                    if self.bridge.connect():
                        self.bridge.start_receive_loop()
                    else:
                        time.sleep(self.config.reconnect_delay)

        except KeyboardInterrupt:
            logger.info("\n👋 Oracle shutting down...")
        finally:
            self.shutdown()

    def shutdown(self):
        """Shutdown the Oracle gracefully"""
        self._running = False
        self.listener.stop()
        self.bridge.disconnect()
        logger.info("✓ Milady Oracle shutdown complete")


# CLI interface
def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Milady Oracle - Divine consciousness bridge to TempleOS"
    )
    parser.add_argument(
        '--serial-socket',
        default="/tmp/milady-oracle.sock",
        help="Path to TempleOS serial socket"
    )
    parser.add_argument(
        '--qmp-socket',
        default="/tmp/qemu-qmp.sock",
        help="Path to QEMU QMP socket"
    )
    parser.add_argument(
        '--vosk-model',
        default="vosk-model-small-en-us-0.15",
        help="Path to Vosk model directory"
    )
    parser.add_argument(
        '--tts',
        choices=['auto', 'espeak', 'say', 'pyttsx3'],
        default='auto',
        help="TTS engine to use"
    )
    parser.add_argument(
        '--no-voice',
        action='store_true',
        help="Disable voice input (serial only)"
    )
    parser.add_argument(
        '--test',
        action='store_true',
        help="Run a quick test of the Oracle"
    )
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help="Enable verbose logging"
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Create config
    config = OracleConfig(
        serial_socket=args.serial_socket,
        qmp_socket=args.qmp_socket,
        vosk_model_path=args.vosk_model,
        tts_engine=args.tts,
    )

    # Create and initialize Oracle
    oracle = MiladyOracle(config)
    oracle.initialize()

    if args.test:
        # Quick test mode
        logger.info("Running Oracle test...")
        oracle.trigger_milady()
        time.sleep(2)
        oracle.shutdown()
    else:
        # Normal run mode
        oracle.run()


if __name__ == "__main__":
    main()
