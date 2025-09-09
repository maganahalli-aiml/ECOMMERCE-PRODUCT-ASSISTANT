from .custom_logger import CustomLogger

# Create a global logger instance
_logger_instance = CustomLogger()
GLOBAL_LOGGER = _logger_instance.get_logger("ProductAssistant")

# Export for easy access
__all__ = ["CustomLogger", "GLOBAL_LOGGER"]