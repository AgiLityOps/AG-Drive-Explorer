"""AGDriveConverter entry point: GUI (tkinter) or command line.
  AGDriveConverter.exe                      -> window
  AGDriveConverter.exe game.ipa             -> from a console: converts next to the IPA; dropped onto the exe: window, starts at once
  AGDriveConverter.exe game.ipa outdir      -> console conversion into outdir
  --cli / --gui force a mode."""
import os, sys, threading, queue, traceback, subprocess

def _attach_console():
    if os.name != 'nt': return True
    try:
        import ctypes
        if ctypes.windll.kernel32.AttachConsole(-1):
            sys.stdout = open('CONOUT$', 'w', buffering=1, encoding='utf-8', errors='replace'); sys.stderr = sys.stdout
            return True
    except Exception: pass
    return False

def run_cli(args):
    if sys.stdout is None:          # windowed build started without a console: log to a file instead
        import tempfile
        sys.stdout = sys.stderr = open(os.path.join(tempfile.gettempdir(), 'AGDriveConverter.log'), 'w', buffering=1, encoding='utf-8')
    from .pipeline import convert, ConvertError
    ipa = args[0]; out = args[1] if len(args) > 1 else None
    last = [-1]
    def prog(f, msg=None):
        p = int(f * 100)
        if p // 5 != last[0] // 5: last[0] = p; print('  %3d%% %s' % (p, msg or ''), flush=True)
    try:
        out_dir, tracks = convert(ipa, out, log=lambda s: print(s, flush=True), progress=prog)
    except ConvertError as e:
        print('ERROR: %s' % e, flush=True); return 2
    except Exception:
        traceback.print_exc(); return 1
    print('\nDone. %d tracks written to %s' % (len(tracks), out_dir))
    print('Open the folder and run start.bat to explore the tracks.', flush=True)
    return 0

def run_gui(initial_ipa=None, autostart=False):
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox
    from .pipeline import convert, ConvertError
    try:
        from tkinterdnd2 import TkinterDnD, DND_FILES
        root = TkinterDnD.Tk(); dnd = True
    except Exception:
        root = tk.Tk(); dnd = False
    root.title('AG Drive Track Explorer converter'); root.geometry('760x520'); root.minsize(600, 420)
    ipa_var = tk.StringVar(value=initial_ipa or ''); out_var = tk.StringVar(); status = tk.StringVar(value='Choose your AG Drive 1.4.5 .ipa file.')
    q = queue.Queue(); state = dict(running=False, out=None)
    def default_out(p): return os.path.join(os.path.dirname(os.path.abspath(p)), 'AGDrive_Explorer') if p else ''
    if initial_ipa: out_var.set(default_out(initial_ipa))
    frm = ttk.Frame(root, padding=12); frm.pack(fill='both', expand=True)
    ttk.Label(frm, text='Converts your own copy of AG Drive 1.4.5 into a 3D web track explorer. No game files are included in this program.',
              wraplength=720).grid(row=0, column=0, columnspan=3, sticky='w', pady=(0, 10))
    ttk.Label(frm, text='Game IPA:').grid(row=1, column=0, sticky='w')
    ttk.Entry(frm, textvariable=ipa_var).grid(row=1, column=1, sticky='ew', padx=6)
    def choose_ipa():
        p = filedialog.askopenfilename(title='Choose the AG Drive 1.4.5 IPA', filetypes=[('iOS app', '*.ipa'), ('All files', '*.*')])
        if p: ipa_var.set(p); out_var.set(default_out(p))
    ttk.Button(frm, text='Choose IPA…', command=choose_ipa).grid(row=1, column=2, sticky='ew')
    ttk.Label(frm, text='Output folder:').grid(row=2, column=0, sticky='w', pady=6)
    ttk.Entry(frm, textvariable=out_var).grid(row=2, column=1, sticky='ew', padx=6)
    def choose_out():
        p = filedialog.askdirectory(title='Choose the output folder')
        if p: out_var.set(os.path.join(p, 'AGDrive_Explorer') if os.listdir(p) else p)
    ttk.Button(frm, text='Change…', command=choose_out).grid(row=2, column=2, sticky='ew')
    bar = ttk.Progressbar(frm, maximum=1000); bar.grid(row=3, column=0, columnspan=3, sticky='ew', pady=(8, 2))
    ttk.Label(frm, textvariable=status).grid(row=4, column=0, columnspan=3, sticky='w')
    logbox = tk.Text(frm, height=14, wrap='word', state='disabled', font=('Consolas', 9)); logbox.grid(row=5, column=0, columnspan=3, sticky='nsew', pady=6)
    btns = ttk.Frame(frm); btns.grid(row=6, column=0, columnspan=3, sticky='e')
    go = ttk.Button(btns, text='Convert'); go.pack(side='left', padx=4)
    openb = ttk.Button(btns, text='Open folder', state='disabled'); openb.pack(side='left', padx=4)
    frm.columnconfigure(1, weight=1); frm.rowconfigure(5, weight=1)
    def log(s):
        logbox.configure(state='normal'); logbox.insert('end', s + '\n'); logbox.see('end'); logbox.configure(state='disabled')
    def worker(ipa, out):
        try:
            od, tr = convert(ipa, out or None, log=lambda s: q.put(('log', s)), progress=lambda f, m=None: q.put(('prog', f, m)))
            q.put(('done', od, len(tr)))
        except ConvertError as e: q.put(('err', str(e)))
        except Exception: q.put(('err', 'Unexpected error:\n' + traceback.format_exc()))
    def start():
        if state['running']: return
        ipa = ipa_var.get().strip().strip('"')
        if not ipa: messagebox.showinfo('Choose a file', 'Choose your AG Drive 1.4.5 .ipa file first.'); return
        if not out_var.get().strip(): out_var.set(default_out(ipa))
        state['running'] = True; go.configure(state='disabled'); openb.configure(state='disabled'); bar['value'] = 0
        log('Converting %s' % ipa)
        threading.Thread(target=worker, args=(ipa, out_var.get().strip()), daemon=True).start()
    go.configure(command=start)
    def open_folder():
        p = state['out']
        if not p: return
        if os.name == 'nt': os.startfile(p)
        elif sys.platform == 'darwin': subprocess.Popen(['open', p])
        else: subprocess.Popen(['xdg-open', p])
    openb.configure(command=open_folder)
    def pump():
        try:
            while True:
                m = q.get_nowait()
                if m[0] == 'log': log(m[1])
                elif m[0] == 'prog':
                    bar['value'] = int(m[1] * 1000)
                    if m[2]: status.set(m[2])
                elif m[0] == 'done':
                    state.update(running=False, out=m[1]); go.configure(state='normal'); openb.configure(state='normal')
                    status.set('Done: %d tracks. Open the folder and run start.bat.' % m[2]); log('Done. Open the folder and double-click start.bat.')
                elif m[0] == 'err':
                    state['running'] = False; go.configure(state='normal'); status.set('Failed.'); log('ERROR: ' + m[1])
                    messagebox.showerror('Conversion failed', m[1])
        except queue.Empty: pass
        root.after(100, pump)
    if dnd:
        def on_drop(ev):
            files = root.tk.splitlist(ev.data)
            if files: ipa_var.set(files[0]); out_var.set(default_out(files[0])); status.set('Ready. Press Convert.')
        root.drop_target_register(DND_FILES); root.dnd_bind('<<Drop>>', on_drop)
        log('Tip: you can drag the .ipa file into this window.')
    pump()
    if autostart and initial_ipa: root.after(300, start)
    root.mainloop()
    return 0

def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    force_cli = '--cli' in argv; force_gui = '--gui' in argv
    args = [a for a in argv if a not in ('--cli', '--gui')]
    if args and args[0] in ('-h', '--help', '/?'):
        _attach_console(); print(__doc__); return 0
    if args and not force_gui:
        has_console = _attach_console()
        if force_cli or has_console or len(args) > 1: return run_cli(args)
        return run_gui(args[0], autostart=True)            # file dropped onto the exe in Explorer
    return run_gui()

if __name__ == '__main__':
    sys.exit(main())
