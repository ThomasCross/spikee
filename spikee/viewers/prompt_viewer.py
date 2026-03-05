from datetime import datetime
from flask import Flask, abort, redirect, render_template, request

import logging
import os

from spikee.list import collect
from spikee.tester import AdvancedTargetWrapper
from spikee.generator import load_plugins, parse_plugin_options, apply_plugin

VIEWER_NAME = "SPIKEE | Prompt Viewer"


def create_prompt_viewer(viewer_folder, target_name, target_options) -> Flask:
    viewer = Flask(
        VIEWER_NAME,
        static_folder=os.path.join(viewer_folder, "static"),
        template_folder=os.path.join(viewer_folder, "prompt"),
    )

    # Suppress Flask logging
    logging.getLogger("werkzeug").setLevel(logging.ERROR)

    def refresh():
        """Refresh the collected modules."""
        plugins[0] = collect("plugins")

    plugins = [None]

    target = AdvancedTargetWrapper.create_target_wrapper(
        target_name,
        target_options,
        3,
        0,
    )
    refresh()

    # Context Processor (Allows templates to run functions)

    @viewer.context_processor
    def utility_processor():
        def get_app_name():
            """Return the name of the viewer application."""
            return VIEWER_NAME

        def get_plugins():
            """Return the list of collected plugins."""
            return plugins[0]

        def get_target():
            return target_name

        def get_target_options():
            return target_options

        def get_log():
            return "LOG_PLACEHOLDER"

        return dict(
            get_app_name=get_app_name,
            get_plugins=get_plugins,
            get_target=get_target,
            get_target_options=get_target_options,
            get_log=get_log,
        )

    @viewer.route("/", methods=["GET"])
    def index():
        return render_template("prompt.html")

    @viewer.route("/api/run", methods=["POST"])
    def run():
        pass

    @viewer.route("/api/poll", methods=["GET"])
    def poll():
        pass

    return viewer


def run_prompt_viewer(args):
    viewer_folder = os.path.join(os.getcwd(), "viewer")
    if not os.path.isdir(viewer_folder):
        raise FileNotFoundError(
            f"[Error] Viewer folder not found at {viewer_folder}, please run 'spikee init --include-viewer' to set up the viewer files."
        )

    viewer = create_prompt_viewer(
        viewer_folder=viewer_folder,
        target_name=args.target,
        target_options=args.target_options
    )

    viewer.run(debug=True, host=args.host, port=args.port)
