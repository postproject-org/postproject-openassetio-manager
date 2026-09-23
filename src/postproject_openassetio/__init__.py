"""OpenAssetIO plugin entry point for the PostProject Manager."""

from openassetio.pluginSystem import PythonPluginSystemManagerPlugin


class PostProjectManagerPlugin(PythonPluginSystemManagerPlugin):
    """Construct the read-only PostProject Manager interface."""

    @staticmethod
    def identifier():
        return "org.postproject.manager"

    @classmethod
    def interface(cls):
        from .manager import PostProjectManagerInterface

        return PostProjectManagerInterface()


openassetioPlugin = PostProjectManagerPlugin
