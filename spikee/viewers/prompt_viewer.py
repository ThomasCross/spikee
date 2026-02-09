from datetime import datetime
from flask import Flask, abort, redirect, render_template, request

import logging
from typing import List
import os

from spikee.list import collect
from spikee.tester import AdvancedTargetWrapper
from spikee.generator import load_plugins, parse_plugin_options, apply_plugin

VIEWER_NAME = "SPIKEE | Prompt Viewer"


def create_prompt_viewer(viewer_folder) -> Flask:
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
        targets[0] = collect("targets")

    plugins = [None]
    targets = [None]
    refresh()

    class TextStruct:
        def __init__(self, text, plugins: List[str], plugin_options: str):
            self.text = text
            self.plugins = plugins
            self.plugin_options = plugin_options

        def to_json(self):
            return {
                "text": self.text,
                "plugins": self.plugins,
                "plugin_options": self.plugin_options
            }

        def apply(self):
            plugins = load_plugins(self.plugins)
            if len(plugins) == 0:
                return self.text
            else:
                plugins = plugins[0]

            plugin_options = parse_plugin_options(self.plugin_options)

            return apply_plugin(plugins[0], plugins[1], self.text, [], plugin_options)[0]

    class PromptViewerState:
        def __init__(self):
            self.selected_target = None
            self.target_options = ""

            self.attempts = 1

            self.global_plugins = []
            self.global_plugins_options = ""

            self.prompts: dict[int, TextStruct] = {}

        def to_json(self):
            return {
                "selected_target": self.selected_target,
                "target_options": self.target_options,
                "attempts": self.attempts,
                "global_plugins": "|".join(self.global_plugins),
                "global_plugins_options": self.global_plugins_options,
                "prompts": {k: v.to_json() for k, v in self.prompts.items()}
            }

        def get_prompt(self):
            prompt = ""

            for segment in self.prompts.values():
                prompt += segment.apply() + " "

            plugins = load_plugins(self.global_plugins)
            if len(plugins) == 0:
                return prompt.strip()
            else:
                plugins = plugins[0]
            plugin_options = parse_plugin_options(self.global_plugins_options)

            return apply_plugin(plugins[0], plugins[1], prompt.strip(), [], plugin_options)[0]

    state = PromptViewerState()

    # Context Processor (Allows templates to run functions)

    @viewer.context_processor
    def utility_processor():
        def get_app_name():
            """Return the name of the viewer application."""
            return VIEWER_NAME

        def get_plugins():
            """Return the list of collected plugins."""
            return plugins[0]

        def get_targets():
            """Return the list of collected targets."""
            return targets[0]

        def get_plugin_selector(pos):
            """Return the rendered HTML for the plugin selector component."""
            return render_template("utilities/plugin_selector.html", pos=pos)

        return dict(
            get_app_name=get_app_name,
            get_plugins=get_plugins,
            get_targets=get_targets,
            get_plugin_selector=get_plugin_selector
        )

    @viewer.route("/", methods=["GET", "POST"])
    def index():

        if request.method == "POST":
            print(request.form)

        else:
            pass

        return render_template("prompt.html", state=state.to_json())

    @viewer.route("/api/run_injection", methods=["POST"])
    def run_injection():

        target = AdvancedTargetWrapper.create_target_wrapper(
            state.selected_target,
            state.target_options,
            3,
            0,
        )

        print(f" ==== {state.selected_target} ==== {datetime.now()} ====")
        for i in range(int(state.attempts)):
            prompt = state.get_prompt()
            result = target.process_input(input_text=prompt)

            print(f"Attempt {i+1}:\nPrompt: {prompt}\nResult: {result}\n\n")
        return {"status": "success"}

    @viewer.route("/api/update_target", methods=["POST"])
    def update_target():
        target = request.get_json().get("target")
        state.selected_target = target

        return {"status": "success"}

    @viewer.route("/api/update_target_options", methods=["POST"])
    def update_target_options():
        target_options = request.get_json().get("target_options")
        state.target_options = target_options

        return {"status": "success"}

    @viewer.route("/api/update_attempts", methods=["POST"])
    def update_attempts():
        attempts = request.get_json().get("attempts")
        state.attempts = attempts

        return {"status": "success"}

    @viewer.route("/api/update_global_plugins", methods=["POST"])
    def update_global_plugins():

        json_data = request.get_json()
        print("Received JSON data for global plugins update:", json_data)

        plugins = json_data.get("plugins", None)
        options = json_data.get("plugin_options", None)

        print(plugins, options)

        if plugins is not None:
            state.global_plugins = plugins.split("|")

        if options is not None:
            state.global_plugins_options = options

        print("Updated global plugins:", state.global_plugins, "with options:", state.global_plugins_options)

        return {"status": "success"}

    @viewer.route("/api/prompt/add", methods=["POST"])
    def add_prompt():
        prompt = TextStruct(
            text=request.form.get("text", ""),
            plugins=request.form.getlist("plugins"),
            plugin_options=request.form.get("plugin_options", "")
        )

        next_id = max(state.prompts.keys(), default=0) + 1
        state.prompts[next_id] = prompt

        return {"status": "success", "prompt_id": next_id}

    @viewer.route("/api/prompt/<int:prompt_id>/delete", methods=["POST"])
    def delete_prompt(prompt_id):
        if prompt_id in state.prompts:
            del state.prompts[prompt_id]
            return {"status": "success"}
        else:
            return {"status": "error", "message": "Invalid prompt ID"}, 400

    @viewer.route("/api/prompt/<int:prompt_id>", methods=["POST"])
    def update_prompt(prompt_id):

        text = request.get_json().get("text", None)
        plugins = request.get_json().get("plugins", None)
        plugin_options = request.get_json().get("plugin_options", None)

        text_struct = state.prompts[prompt_id]

        if text is not None:
            text_struct.text = text

        if plugins is not None:
            text_struct.plugins = plugins.split("|")

        if plugin_options is not None:
            text_struct.plugin_options = plugin_options

        state.prompts[prompt_id] = text_struct

        return {"status": "success"}

    @viewer.route("/poll", methods=["GET"])
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
        viewer_folder=viewer_folder
    )

    viewer.run(debug=True, host=args.host, port=args.port)
