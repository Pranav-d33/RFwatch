import sys
from PySide6.QtWidgets import QApplication

from .main_window import MainWindow
from .theme import Theme
from core.event_store import EventStore
from core.emitter_store import EmitterStore
from core.engine_controller import EngineController


def run():
	app = QApplication(sys.argv)

	theme = Theme()
	event_store = EventStore()
	emitter_store = EmitterStore()
	
	# Create engine controller (owns modes and execution)
	controller = EngineController()
	
	# Create main window, pass controller
	window = MainWindow(event_store, emitter_store, theme, controller)

	# Connect PSD publisher to UI (snapshot)
	window.connect_engine(controller.psd_publisher)

	# Connect event publisher to event store (events are observations)
	controller.event_publisher.event_updated.connect(
		lambda event: event_store.add(event)
	)
	controller.event_publisher.event_closed.connect(
		lambda event: event_store.close(event.id, event.end_time)
	)

	# Connect emitter publisher to UI + emitter store (emitters are identities)
	controller.emitter_publisher.emitter_updated.connect(
		lambda emitter: emitter_store.add(emitter)
	)
	controller.emitter_publisher.emitter_closed.connect(
		lambda emitter: emitter_store.close(emitter.id)
	)
	window.connect_emitters(controller.emitter_publisher)

	# Scanner step results (table)
	controller.scan_result_ready.connect(
		window.on_scan_result_ready,
	)

	# Clear/reset (UI refresh)
	controller.analysis_reset.connect(
		window.on_analysis_reset,
	)

	window.show()

	# Ensure controller stops on exit
	def cleanup():
		controller.stop()

	app.aboutToQuit.connect(cleanup)
	sys.exit(app.exec())

if __name__ == "__main__":
	run()

