import os

filepath = "main.py"
with open(filepath, "r", encoding="utf-8") as f:
    content = f.read()

# Chunk 1: init vars
content = content.replace(
'''        self._scanner: DuplicateScanner | None = None
        self._pending_pairs: list[tuple[Path, Path]] = []
        self._current_pair: tuple[Path, Path] | None = None
        self._scan_running = False
        self._scan_done = False
        self._pair_index = 0  # displayed pair counter''',
'''        self._scanner: DuplicateScanner | None = None
        self._pending_groups: list[list[Path]] = []
        self._current_group: list[Path] | None = None
        self._scan_running = False
        self._scan_done = False
        self._group_index = 0  # displayed group counter
        self._dup_panels: list[ImagePanel] = []
        self._dup_vars: list[tk.StringVar] = []'''
)

# Chunk 2: _build_main_area duplicate scanner area
old_dup_area = '''        # ── 1. Duplicate Scanner Area ─────────────────────
        self._frame_dup_area = tk.Frame(self._main_container, bg=BG_DARK)
        self._frame_dup_area.columnconfigure(0, weight=3)
        self._frame_dup_area.columnconfigure(1, weight=2)
        self._frame_dup_area.columnconfigure(2, weight=3)
        self._frame_dup_area.rowconfigure(0, weight=1)

        self.panel_left  = ImagePanel(self._frame_dup_area, "◀  Image 1", rotate_hotkey="Q")
        self.panel_left.grid(row=0, column=0, sticky="nsew", padx=(0, 6))

        self._build_action_panel(self._frame_dup_area)

        self.panel_right = ImagePanel(self._frame_dup_area, "Image 2  ▶", rotate_hotkey="E")
        self.panel_right.grid(row=0, column=2, sticky="nsew", padx=(6, 0))

        self._frame_dup_area.pack(fill="both", expand=True, padx=20, pady=15)'''

new_dup_area = '''        # ── 1. Duplicate Scanner Area ─────────────────────
        self._frame_dup_area = tk.Frame(self._main_container, bg=BG_DARK)
        
        dup_action_bar = tk.Frame(self._frame_dup_area, bg=BG_PANEL, pady=10)
        dup_action_bar.pack(fill="x", side="top")
        
        self.lbl_group_counter = tk.Label(dup_action_bar, text="", font=(FONT_FAMILY, 10, "bold"), bg=BG_PANEL, fg=TEXT_DIM)
        self.lbl_group_counter.pack(side="left", padx=15)
        
        self._btn_keep_all = self._make_button(dup_action_bar, "✅ Keep All (W)", self._act_keep_all, fg="#ffffff", bg=COLOR_BOTH_KEEP)
        self._btn_keep_all.pack(side="left", padx=5)
        
        self._btn_trash_all = self._make_button(dup_action_bar, "🗑 Trash All (S)", self._act_trash_all, fg="#ffffff", bg=COLOR_BOTH_TRASH)
        self._btn_trash_all.pack(side="left", padx=5)
        
        self._btn_next_group = self._make_button(dup_action_bar, "Confirm & Next Group ➔ (Enter)", self._act_next_group, fg="#ffffff", bg=ACCENT_BLUE)
        self._btn_next_group.pack(side="right", padx=15)
        
        self.dup_canvas = tk.Canvas(self._frame_dup_area, bg=BG_DARK, highlightthickness=0)
        self.dup_scrollbar = ttk.Scrollbar(self._frame_dup_area, orient="horizontal", command=self.dup_canvas.xview)
        self.dup_container = tk.Frame(self.dup_canvas, bg=BG_DARK)
        
        self.dup_canvas_window = self.dup_canvas.create_window((0, 0), window=self.dup_container, anchor="nw")
        self.dup_canvas.configure(xscrollcommand=self.dup_scrollbar.set)
        
        self.dup_container.bind("<Configure>", lambda e: self.dup_canvas.configure(scrollregion=self.dup_canvas.bbox("all")))
        self.dup_canvas.bind("<Configure>", lambda e: self.dup_canvas.itemconfig(self.dup_canvas_window, height=e.height))
        
        self.dup_scrollbar.pack(side="bottom", fill="x")
        self.dup_canvas.pack(side="top", fill="both", expand=True)

        self._frame_dup_area.pack(fill="both", expand=True, padx=20, pady=15)'''
content = content.replace(old_dup_area, new_dup_area)

# Remove _build_action_panel completely
import re
content = re.sub(r'    def _build_action_panel\(self, parent\):.*?        self\.lbl_similarity\.pack\(\)\n', '', content, flags=re.DOTALL)

# Chunk 3: Queue polling & pair management (replace _poll_queue to _show_complete_state)
old_poll = '''    # ── Queue polling (called by Tk event loop) ─────────────────────────────
    def _poll_queue(self):
        # Drain all available items
        try:
            while True:
                item = self._scan_queue.get_nowait()
                if item is SCAN_DONE:
                    self._scan_running = False
                    self._scan_done = True
                    self._on_scan_finished()
                    return  # stop polling
                else:
                    a, b = item
                    self._match_counts[a] = self._match_counts.get(a, 0) + 1
                    self._match_counts[b] = self._match_counts.get(b, 0) + 1
                    self._pending_pairs.append(item)
                    # Load pair immediately if none being shown
                    if self._current_pair is None:
                        self._load_next_pair()
        except queue.Empty:
            pass

        # Update progress
        total, processed, pairs = self._stats.snapshot()
        if total > 0:
            pct = int(processed / total * 100)
            self.progress_var.set(pct)
            self.lbl_progress.config(text=f"{processed}/{total}")
            self._update_status(
                f"🔍  Scanning… {processed}/{total} files  |  {pairs} duplicate pair(s) found so far"
            )

        # Schedule next poll
        self.after(POLL_MS, self._poll_queue)

    def _on_scan_finished(self):
        total, _, pairs = self._stats.snapshot()
        self.progress_var.set(100)
        self.lbl_progress.config(text=f"{total}/{total}")
        self._btn_browse.config(state="normal")
        self._btn_scan.config(state="normal")

        if self._current_pair is None:
            if not self._pending_pairs:
                self._show_complete_state("No duplicate images found in the selected directory.")
            else:
                self._load_next_pair()
        else:
            self._update_status(
                f"Scan complete — {pairs} pair(s) found. Reviewing…"
            )

    # ── Pair management ─────────────────────────────────────────────────────
    def _purge_deleted(self, *paths: Path):
        """
        Remove any pending pairs that reference one of the given (just-deleted)
        paths so we never try to load a file that no longer exists.
        """
        deleted = {str(p) for p in paths}
        self._pending_pairs = [
            (a, b) for a, b in self._pending_pairs
            if str(a) not in deleted and str(b) not in deleted
        ]

    def _load_next_pair(self):
        # Skip over pairs where either file has been deleted elsewhere.
        while self._pending_pairs:
            candidate = self._pending_pairs[0]
            if candidate[0].exists() and candidate[1].exists():
                break  # good pair — use it
            # One or both files are already gone; silently discard this pair.
            self._pending_pairs.pop(0)

        if not self._pending_pairs:
            if self._scan_done:
                self._show_complete_state()
            else:
                # Scan still running; wait for more results
                self._current_pair = None
                self.panel_left.show_placeholder("Scanning for more\\nduplicates…")
                self.panel_right.show_placeholder("Scanning for more\\nduplicates…")
                self._set_review_state(active=False)
            return

        pair = self._pending_pairs.pop(0)
        self._current_pair = pair
        self._pair_index += 1
        left_path, right_path = pair

        self.panel_left.load_image(left_path)
        self.panel_right.load_image(right_path)

        # Update match counts
        count_left = self._match_counts.get(left_path, 1)
        count_right = self._match_counts.get(right_path, 1)
        self.panel_left.lbl_match_count.config(text=f"Matched with {count_left} picture(s) total")
        self.panel_right.lbl_match_count.config(text=f"Matched with {count_right} picture(s) total")

        # Compute and show similarity
        sim_text = self._similarity_label(left_path, right_path)
        self.lbl_similarity.config(text=sim_text)

        self.lbl_pair_counter.config(text=f"Pair {self._pair_index}")
        self._set_review_state(active=True)

        self._update_status(
            f"Reviewing pair {self._pair_index}  |  {len(self._pending_pairs)} pair(s) remaining in queue"
        )

    def _show_complete_state(self, msg: str = ""):
        self._current_pair = None
        self._set_review_state(active=False)
        if not msg:
            msg = (
                f"✅  All done!\\n{self._pair_index} pair(s) reviewed.\\n\\n"
                "No more duplicates found."
            )
        self.panel_left.show_placeholder(msg)
        self.panel_right.show_placeholder(msg)
        self.lbl_pair_counter.config(text="")
        self.lbl_similarity.config(text="")
        self._update_status(f"Scan complete — {self._pair_index} pair(s) reviewed.")
        self.progress_var.set(100)'''

new_poll = '''    # ── Queue polling (called by Tk event loop) ─────────────────────────────
    def _poll_queue(self):
        try:
            while True:
                item = self._scan_queue.get_nowait()
                if item is SCAN_DONE:
                    self._scan_running = False
                    self._scan_done = True
                    self._on_scan_finished()
                    return
                else:
                    for p in item:
                        self._match_counts[p] = self._match_counts.get(p, 0) + 1
                    self._pending_groups.append(item)
                    if self._current_group is None:
                        self._load_next_group()
        except queue.Empty:
            pass

        total, processed, groups_found = self._stats.snapshot()
        if total > 0:
            pct = int(processed / total * 100)
            self.progress_var.set(pct)
            self.lbl_progress.config(text=f"{processed}/{total}")
            self._update_status(f"🔍  Scanning… {processed}/{total} files  |  {groups_found} duplicate group(s) found so far")

        self.after(POLL_MS, self._poll_queue)

    def _on_scan_finished(self):
        total, _, groups_found = self._stats.snapshot()
        self.progress_var.set(100)
        self.lbl_progress.config(text=f"{total}/{total}")
        self._btn_browse.config(state="normal")
        self._btn_scan.config(state="normal")

        if self._current_group is None:
            if not self._pending_groups:
                self._show_complete_state("No duplicate images found in the selected directory.")
            else:
                self._load_next_group()
        else:
            self._update_status(f"Scan complete — {groups_found} group(s) found. Reviewing…")

    # ── Group management ─────────────────────────────────────────────────────
    def _purge_deleted(self, *paths: Path):
        deleted = {str(p) for p in paths}
        new_pending = []
        for group in self._pending_groups:
            valid = [p for p in group if str(p) not in deleted]
            if len(valid) > 1:
                new_pending.append(valid)
        self._pending_groups = new_pending

    def _load_next_group(self):
        while self._pending_groups:
            candidate = self._pending_groups[0]
            valid = [p for p in candidate if p.exists()]
            if len(valid) > 1:
                self._pending_groups[0] = valid
                break
            self._pending_groups.pop(0)

        if not self._pending_groups:
            if self._scan_done:
                self._show_complete_state()
            else:
                self._current_group = None
                self._clear_dup_panels()
                self._set_review_state(active=False)
            return

        group = self._pending_groups.pop(0)
        self._current_group = group
        self._group_index += 1
        
        self._clear_dup_panels()
        for idx, path in enumerate(group):
            panel_frame = tk.Frame(self.dup_container, bg=BG_DARK)
            panel_frame.pack(side="left", fill="y", padx=5)
            
            pnl = ImagePanel(panel_frame, f"Image {idx+1}", rotate_hotkey="", preview_size=(400, 460))
            pnl.pack(side="top", fill="both", expand=True)
            pnl.load_image(path)
            count = self._match_counts.get(path, 1)
            pnl.lbl_match_count.config(text=f"Matched with {count} picture(s)")
            
            var = tk.StringVar(value="keep")
            self._dup_vars.append(var)
            
            rb_frame = tk.Frame(panel_frame, bg=BG_PANEL, pady=5)
            rb_frame.pack(side="bottom", fill="x")
            
            rb_keep = tk.Radiobutton(rb_frame, text="Keep", variable=var, value="keep", bg=BG_PANEL, fg=ACCENT_GREEN, selectcolor=BG_DARK)
            rb_keep.pack(side="left", expand=True)
            rb_trash = tk.Radiobutton(rb_frame, text="Trash", variable=var, value="trash", bg=BG_PANEL, fg=ACCENT_RED, selectcolor=BG_DARK)
            rb_trash.pack(side="right", expand=True)
            
            self._dup_panels.append(pnl)

        self.lbl_group_counter.config(text=f"Group {self._group_index}")
        self._set_review_state(active=True)
        self._update_status(f"Reviewing group {self._group_index}  |  {len(self._pending_groups)} group(s) remaining in queue")

    def _clear_dup_panels(self):
        for widget in self.dup_container.winfo_children():
            widget.destroy()
        self._dup_panels.clear()
        self._dup_vars.clear()

    def _show_complete_state(self, msg: str = ""):
        self._current_group = None
        self._set_review_state(active=False)
        self._clear_dup_panels()
        if not msg:
            msg = f"✅  All done!\\n{self._group_index} group(s) reviewed.\\n\\nNo more duplicates found."
        
        placeholder = tk.Label(self.dup_container, text=msg, font=(FONT_FAMILY, 14, "bold"), bg=BG_DARK, fg=ACCENT_GREEN, justify="center")
        placeholder.pack(expand=True, fill="both", pady=50, padx=50)
        self.lbl_group_counter.config(text="")
        self._update_status(f"Scan complete — {self._group_index} group(s) reviewed.")
        self.progress_var.set(100)'''
content = content.replace(old_poll, new_poll)

# Chunk 4: Actions callbacks
old_actions = '''    # ── Action button callbacks ─────────────────────────────────────────────
    def _act_keep_both(self):
        self._advance()

    def _act_keep_left(self):
        if not self._current_pair:
            self._advance()
            return
        right = self._current_pair[1]
        self._set_review_state(active=False)  # block double-clicks during flash
        self.panel_left.flash_green()
        self.update_idletasks()               # force repaint NOW before advancing
        send_to_trash(right)
        self._purge_deleted(right)
        self.after(FLASH_MS, self._advance)

    def _act_keep_right(self):
        if not self._current_pair:
            self._advance()
            return
        left = self._current_pair[0]
        self._set_review_state(active=False)
        self.panel_right.flash_green()
        self.update_idletasks()
        send_to_trash(left)
        self._purge_deleted(left)
        self.after(FLASH_MS, self._advance)

    def _act_trash_both(self):
        if self._current_pair:
            left, right = self._current_pair
            send_to_trash(left)
            send_to_trash(right)
            self._purge_deleted(left, right)
        self._advance()

    def _act_del_left(self):
        if not self._current_pair:
            return
        path = self._current_pair[0]
        if messagebox.askyesno(
            "Permanent Delete",
            f"Permanently delete (NO Recycle Bin):\\n\\n{path}\\n\\nThis cannot be undone!",
        ):
            delete_permanent(path)
            self._purge_deleted(path)
            self._advance()

    def _act_del_right(self):
        if not self._current_pair:
            return
        path = self._current_pair[1]
        if messagebox.askyesno(
            "Permanent Delete",
            f"Permanently delete (NO Recycle Bin):\\n\\n{path}\\n\\nThis cannot be undone!",
        ):
            delete_permanent(path)
            self._purge_deleted(path)
            self._advance()

    def _advance(self):
        self._current_pair = None
        self._load_next_pair()'''

new_actions = '''    # ── Action button callbacks ─────────────────────────────────────────────
    def _act_keep_all(self):
        for var in self._dup_vars:
            var.set("keep")

    def _act_trash_all(self):
        for var in self._dup_vars:
            var.set("trash")

    def _act_next_group(self):
        if not self._current_group:
            self._load_next_group()
            return
            
        self._set_review_state(active=False)
        trashed_paths = []
        for i, var in enumerate(self._dup_vars):
            if var.get() == "trash":
                path = self._current_group[i]
                trashed_paths.append(path)
                send_to_trash(path)
                
        if trashed_paths:
            self._purge_deleted(*trashed_paths)
            
        self.after(200, self._load_next_group)'''
content = content.replace(old_actions, new_actions)

# Chunk 5: Keypress events
old_keys = '''            if char == 'w':
                self._act_keep_both()
            elif char == 'a':
                self._act_keep_left()
            elif char == 's':
                self._act_trash_both()
            elif char == 'd':
                self._act_keep_right()
            elif char == 'q':
                self.panel_left.rotate_image()
            elif char == 'e':
                self.panel_right.rotate_image()'''
new_keys = '''            if char == 'w':
                self._act_keep_all()
            elif char == 's':
                self._act_trash_all()
            elif char == '\\r':
                self._act_next_group()
            elif char.isdigit() and int(char) >= 1 and int(char) <= len(self._dup_vars):
                idx = int(char) - 1
                current = self._dup_vars[idx].get()
                self._dup_vars[idx].set("trash" if current == "keep" else "keep")'''
content = content.replace(old_keys, new_keys)

# Set review state
old_review = '''    def _set_review_state(self, active: bool):
        state = "normal" if active else "disabled"
        for btn in self._action_buttons:
            btn.config(state=state)'''
new_review = '''    def _set_review_state(self, active: bool):
        state = "normal" if active else "disabled"
        if hasattr(self, '_btn_keep_all'):
            self._btn_keep_all.config(state=state)
            self._btn_trash_all.config(state=state)
            self._btn_next_group.config(state=state)'''
content = content.replace(old_review, new_review)

with open(filepath, "w", encoding="utf-8") as f:
    f.write(content)
print("Main.py patched successfully.")
