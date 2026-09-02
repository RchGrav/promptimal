# Standard library
import time
import asyncio
import difflib
from typing import List, Optional, Tuple

# Third party
import urwid
import pyperclip

# Local
try:
    from promptimal.optimizer import optimize
    from promptimal.dtos import ProgressStep
except ImportError:
    from optimizer import optimize
    from dtos import ProgressStep


#########
# HELPERS
#########


class ScrollableListBox(urwid.ListBox):
    def keypress(self, size, key):
        if key in ("up", "down", "page up", "page down"):
            return super().keypress(size, key)

        return key


class PromptBox:
    def __init__(self, prompt: str):
        # Raw state
        self.show_diff = True
        self.init_prompt = prompt
        self.curr_prompt = prompt
        self.loading_task = None  # Controls loading indicator when score is N/A
        self.loop = None  # Parent event loop

        # Widgets
        self.prompt_widget = ScrollableListBox(
            urwid.SimpleFocusListWalker(self._create_prompt())
        )
        self.score = urwid.Text(self._create_score())
        self.options = urwid.Text(self._create_options(prompt), align="right")
        menu = urwid.Columns(
            [("weight", 1, self.score), ("pack", self.options)], dividechars=1
        )
        frame = urwid.Padding(
            urwid.Pile(
                [
                    ("pack", urwid.Divider(" ", top=0, bottom=0)),
                    urwid.Frame(body=self.prompt_widget, footer=menu),
                ]
            ),
            left=1,
            right=1,
        )
        self.widget = urwid.LineBox(
            frame,
            title="Best Prompt",
            title_align="left",
            title_attr="secondary bold",
        )

    async def _animate_ellipsis(self):
        ellipsis_states = ["   ", ".  ", ".. ", "..."]
        index = 0
        while True:
            self.score.set_text(
                ["\n", ("tertiary", "Score: "), ("secondary", ellipsis_states[index])]
            )
            self.loop.draw_screen()
            index = (index + 1) % len(ellipsis_states)
            await asyncio.sleep(0.5)

    def _create_score(self, score: Optional[float] = None) -> List[Tuple[str, str]]:
        if score == None:
            return ["\n", ("tertiary", "Score: "), ("secondary", "...")]

        score_attr = "score ok"
        if score <= 0.33:
            score_attr = "score bad"
        elif score >= 0.67:
            score_attr = "score good"

        return [
            ("default", "\n"),
            ("tertiary", "Score: "),
            (score_attr, f"{(score * 100):.2f}%"),
        ]

    def _create_prompt(self, prompt: Optional[str] = None) -> List[Tuple[str, str]]:
        prompt = prompt if prompt else self.curr_prompt

        if not self.show_diff or prompt == self.init_prompt:
            return [urwid.Text(("default", line)) for line in prompt.split("\n")]

        diff = difflib.ndiff(self.init_prompt, prompt)
        diffed_lines, current_line = [], []
        for item in diff:
            code, char = item[0], item[2:]

            if code == " ":  # Unchanged
                current_line.append(char)
            elif code == "+":  # Added
                current_line.append(("diff added", char))
            elif code == "-":  # Deleted
                current_line.append(("diff removed", char))

            if char.endswith("\n"):
                last_char = current_line[-1]
                if isinstance(last_char, tuple):
                    last_char = last_char[1]

                if last_char == "\n":
                    current_line[-1] = ("default", "")

                diffed_lines.append(current_line)
                current_line = []

        if current_line:
            diffed_lines.append(current_line)

        diff_widgets = []
        for line in diffed_lines:
            last_char = line[-1]
            if isinstance(last_char, tuple):
                last_char = last_char[1]

            if last_char == "\n":
                line[-1] = ("default", "")

            diff_widgets.append(urwid.Text(line))

        return diff_widgets

    def _create_options(self, prompt: str) -> List[Tuple[str, str]]:
        options = [
            "\n",
            ("menu", " C "),
            ("secondary", " Copy to clipboard"),
        ]
        if prompt != self.init_prompt:
            options.extend(
                [
                    " ",
                    ("menu", " D "),
                    ("secondary", " Hide diff" if self.show_diff else " Show diff"),
                ]
            )

        # TODO: Make this conditional
        options.extend(
            [
                " ",
                ("menu", " ↑ ↓ "),
                ("secondary", " Scroll"),
            ]
        )

        return options

    def update(
        self,
        prompt: Optional[str] = None,
        score: Optional[float] = None,
        show_diff: Optional[bool] = None,
    ):
        if score != None:
            if self.loading_task:
                self.loading_task.cancel()
                self.loading_task = None

            self.score.set_text(self._create_score(score))

        if prompt != None:
            self.curr_prompt = prompt
            self.prompt_widget.body[:] = urwid.SimpleFocusListWalker(
                self._create_prompt()
            )
            self.options.set_text(self._create_options(prompt))

        if show_diff != None:
            self.show_diff = show_diff
            self.prompt_widget.body[:] = urwid.SimpleFocusListWalker(
                self._create_prompt()
            )
            self.options.set_text(self._create_options(prompt))

    async def run(self, loop: urwid.AsyncioEventLoop):
        self.loop = loop
        self.loading_task = asyncio.ensure_future(self._animate_ellipsis())


class ProgressBox:
    def __init__(self, steps: List[ProgressStep]):
        self.rows = urwid.ListBox([self._create_row(step) for step in steps])
        padded_rows = urwid.Pile(
            [("pack", urwid.Divider(" ", top=0, bottom=0)), self.rows]
        )
        self.widget = padded_rows

        self.loop = None  # Parent event loop

    def _format_elapsed_time(
        self, start_time: float, end_time: Optional[float] = None
    ) -> str:
        if not end_time:
            return "--:--:--"

        elapsed_seconds = int(end_time - start_time)
        hours, remainder = divmod(elapsed_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{hours:02}:{minutes:02}:{seconds:02}"

    def _create_row(self, step: ProgressStep) -> urwid.Filler:
        label_text = f"{step.message}: "
        label_attr = "score good"
        if not step.index:
            label_attr = "secondary"
        elif step.is_terminal:
            label_attr = "purple"
            label_text = step.message

        label = urwid.Text((label_attr, label_text))

        if step.is_terminal:
            return urwid.Padding(label, left=2, right=2)

        progress_bar = urwid.ProgressBar(
            "pg normal", "pg complete", current=step.value * 100, done=100
        )
        elapsed_time = self._format_elapsed_time(step.start_time, step.end_time)

        columns = urwid.Columns(
            [(25, label), progress_bar, (8, urwid.Text(("secondary", elapsed_time)))],
            dividechars=1,
        )
        columns = urwid.Padding(columns, left=2, right=2)
        row = urwid.Filler(columns, valign="top")
        row = urwid.Pile([row, urwid.Divider(" ", top=0, bottom=0)])
        return row

    def update(self, steps: List[ProgressStep]):
        new_rows = [self._create_row(step) for step in steps]
        self.rows.body[:] = new_rows

    async def run(self, loop: urwid.AsyncioEventLoop):
        self.loop = loop


class Footer:
    def __init__(self, steps: List[ProgressStep]):
        terminate = urwid.Text(
            [
                ("menu", " ESC "),
                ("secondary", " Exit"),
            ],
            align="left",
        )
        self.counter = urwid.Text(self._create_counter(steps[-1]), align="right")
        self.widget = urwid.Padding(
            urwid.Columns(
                [("weight", 1, terminate), ("pack", self.counter)], dividechars=1
            ),
            left=1,
            right=1,
        )

    def _create_counter(self, step: ProgressStep) -> List[Tuple[str, str]]:
        input_toks = step.token_count.input if step.token_count else 0
        output_toks = step.token_count.output if step.token_count else 0
        num_tokens = input_toks + output_toks
        cost = step.token_count.cost if step.token_count else 0.0

        return [
            ("tertiary", f"{step.num_prompts} prompts evaluated"),
            (
                "tertiary bold",
                f" | ${cost:.2f} ({num_tokens} tokens)",
            ),
        ]

    def update(self, steps: List[ProgressStep]):
        self.counter.set_text(self._create_counter(steps[-1]))


######
# MAIN
######


class App:
    def __init__(self, init_prompt: str):
        # State
        self.is_finished = False
        self.prompt = init_prompt
        self.score = None
        self.steps = [
            ProgressStep(
                index=0,
                value=0.0,
                message="Starting optimization",
                best_prompt=init_prompt,
                start_time=time.time(),
            )
        ]

        # Initialize widgets
        self.prompt_box = PromptBox(self.prompt)
        self.progress_box = ProgressBox(self.steps)
        self.footer = Footer(self.steps)
        layout = urwid.Frame(
            body=urwid.Pile(
                [
                    ("weight", 1, self.prompt_box.widget),
                    ("weight", 1, self.progress_box.widget),
                ]
            ),
            footer=self.footer.widget,
        )
        palette = [
            ("menu", "black", "dark green", "standout"),
            ("pg normal", "black", "dark gray", "standout"),
            ("pg complete", "black", "dark green", "standout"),
            ("secondary", "light gray", "default", "standout"),
            ("secondary bold", "light gray, bold", "default", "standout"),
            ("tertiary", "dark gray", "default", "standout"),
            ("tertiary bold", "dark gray, bold", "default", "standout"),
            ("score bad", "light red", "default", "standout"),
            ("score ok", "yellow", "default", "standout"),
            ("score good", "light green", "default", "standout"),
            ("purple", "dark magenta, bold", "default", "standout"),
            ("diff added", "dark green", "default", "standout"),
            ("diff removed", "dark red", "default", "standout"),
        ]

        # Create event loop, pass on to widgets
        self.loop = urwid.MainLoop(
            layout,
            palette,
            unhandled_input=self.handle_input,
            event_loop=urwid.AsyncioEventLoop(loop=asyncio.get_event_loop()),
        )

    def update(self):
        self.prompt_box.update(self.prompt, self.score)
        self.progress_box.update(self.steps)
        self.footer.update(self.steps)
        self.loop.draw_screen()

    def handle_input(self, key: str):
        if key in ("q", "Q", "esc"):
            raise urwid.ExitMainLoop()
        elif key in ("c", "C"):
            pyperclip.copy(self.prompt)
            urwid.emit_signal(self, "message", "Prompt copied to clipboard.")
        elif key in ("d", "D"):
            self.prompt_box.update(show_diff=not self.prompt_box.show_diff)
            self.loop.draw_screen()

    async def optimize(self, **kwargs):
        async for step in optimize(self.prompt, **kwargs):
            # Update state
            self.prompt = step.best_prompt.replace("\\n", "\n")
            self.score = step.best_score
            existing_step = next((s for s in self.steps if s.index == step.index), None)
            if existing_step:
                existing_step.value = step.value
                existing_step.message = step.message
                existing_step.token_count = step.token_count
                existing_step.num_prompts = step.num_prompts
                existing_step.end_time = step.end_time
            else:
                self.steps.append(step)

            # # Update widgets and yield control to event loop
            self.update()
            await asyncio.sleep(0)

        self.is_finished = True

    def start(self, **kwargs) -> Tuple[str, bool]:
        asyncio.ensure_future(self.prompt_box.run(self.loop))
        asyncio.ensure_future(self.progress_box.run(self.loop))
        asyncio.ensure_future(self.optimize(**kwargs))

        self.loop.run()

        return self.prompt, self.is_finished
