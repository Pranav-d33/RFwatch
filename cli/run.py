"""
CLI entry point.
"""

import argparse
import time
import sys
from core.engine_controller import EngineController, InspectorConfig, ControllerState
from utils.logging import setup_logging

def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(description="RF Inspector CLI")
    parser.add_argument(
        "--duration", type=float, default=10, help="Run duration in seconds"
    )
    parser.add_argument(
        "--freq", type=float, default=100e6, help="Center frequency in Hz"
    )
    parser.add_argument(
        "--sample-rate",
        type=float,
        default=2e6,
        help="Sample rate in Hz",
    )
    parser.add_argument(
        "--gain", type=float, default=40.0, help="Gain in dB"
    )

    args = parser.parse_args()

    # Setup
    logger = setup_logging()
    
    try:
        controller = EngineController()
    except Exception as e:
        logger.error(f"Failed to initialize controller: {e}")
        sys.exit(1)

    if not controller.use_hackrf:
        logger.error("HackRF not detected. CLI requires hardware.")
        sys.exit(1)

    # Configure Inspector
    config = InspectorConfig(
        center_freq=args.freq,
        sample_rate=args.sample_rate,
        gain=args.gain
    )

    logger.info(f"Starting Inspector on {args.freq/1e6} MHz for {args.duration}s...")
    
    try:
        controller.start_inspector(config)
    except Exception as e:
        logger.error(f"Failed to start inspector: {e}")
        sys.exit(1)

    # Run for duration
    start_time = time.time()
    try:
        while time.time() - start_time < args.duration:
            time.sleep(0.5)
            # We could print stats here if we hooked into signals
    except KeyboardInterrupt:
        pass
    finally:
        controller.stop()
        logger.info("Stopped.")

if __name__ == "__main__":
    main()
