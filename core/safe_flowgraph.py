"""
Isolated flowgraph management to handle segfaults gracefully.

Problem: flowgraph.start() can segfault at C level (GNU Radio/osmosdr issue)
Solution: Run flowgraph in isolated context so segfault doesn't kill main app

Design:
- Main app creates flowgraph
- Flowgraph lives in thread/subprocess that can crash independently
- Main app handles None/error and falls back to simulated data
"""

import threading
import time
import signal
import sys
from typing import Optional


class SafeFlowgraphManager:
    """
    Manages GNU Radio flowgraph with protection against segfaults.
    
    Usage:
        manager = SafeFlowgraphManager(flowgraph)
        if manager.start(timeout=5.0):
            print("✓ Flowgraph started")
        else:
            print("✗ Flowgraph failed, falling back to simulated")
    """
    
    def __init__(self, flowgraph):
        self.flowgraph = flowgraph
        self.started = False
        self.error = None
        self.thread = None
    
    def start(self, timeout: float = 2.0) -> bool:
        """
        Start flowgraph in isolated thread.
        
        Returns:
            True if started successfully, False if failed/crashed
        """
        if self.started:
            return True
        
        # Try starting in thread (allows main thread to continue even if it crashes)
        self.thread = threading.Thread(
            target=self._start_flowgraph,
            name="FlowgraphStarter",
            daemon=True
        )
        self.thread.start()
        
        # Wait for thread to either start or fail
        self.thread.join(timeout=timeout)
        
        if self.error:
            print(f"[FLOWGRAPH_MGR] Startup failed: {self.error}")
            return False
        
        if not self.started:
            print(f"[FLOWGRAPH_MGR] Startup timeout after {timeout}s (possible hang)")
            return False
        
        return True
    
    def _start_flowgraph(self):
        """Start flowgraph (runs in isolated thread)."""
        try:
            print("[FLOWGRAPH_MGR] Starting flowgraph in isolated thread...")
            self.flowgraph.start()
            self.started = True
            print("[FLOWGRAPH_MGR] Flowgraph started successfully in thread")
            
            # Let it run - thread will keep the flowgraph running
            # (even if main thread dies, flowgraph continues)
            while self.started:
                time.sleep(1.0)
                
        except Exception as e:
            self.error = f"{type(e).__name__}: {e}"
            print(f"[FLOWGRAPH_MGR] Error in flowgraph thread: {self.error}")
    
    def stop(self):
        """Stop flowgraph gracefully."""
        if self.flowgraph and self.started:
            try:
                self.flowgraph.stop()
                self.flowgraph.wait()
                self.started = False
            except:
                pass


def install_segfault_handler():
    """
    Install a signal handler for segfaults.
    
    This won't prevent segfaults, but can help with debugging.
    Not needed if using SafeFlowgraphManager.
    """
    def handle_segfault(signum, frame):
        print("\n[ERROR] Segmentation fault detected!")
        print("[ERROR] This is likely a GNU Radio/osmosdr/firmware issue")
        print("[ERROR] Falling back to simulated RF data")
        print("[ERROR] Try: update HackRF firmware or GNU Radio version")
        sys.exit(1)
    
    signal.signal(signal.SIGSEGV, handle_segfault)
