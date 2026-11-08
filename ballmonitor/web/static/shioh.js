// Shioh style helpers: the phone menu, ssToast() and ssConfirm(). Load with <script defer>, and put
//   <script>document.documentElement.classList.add('ss-js')</script>
// in <head> so the phone menu starts closed without a flash.
//
//   ssToast('Copied');                         // white chip, bottom-right (bottom-centre on phones)
//   ssToast('Could not save', { error: true, timeout: 6000 });
//   if (await ssConfirm('Start this farm over?', { title: 'Start over', ok: 'Start over' })) restart();
//
// Code that may run without this file can fall back to the browser's own boxes:
//   const ask = window.ssConfirm || ((m) => Promise.resolve(confirm(m)));
(function () {
	document.documentElement.classList.add('ss-js');

	// ---- Phone menu: .ss-navcell > .ss-logo + button.ss-menu-btn + .ss-nav ----
	function setupMenus() {
		document.querySelectorAll('.ss-menu-btn').forEach(function (btn) {
			var cell = btn.closest('.ss-navcell');
			if (!cell || btn.dataset.ssMenu) return;
			btn.dataset.ssMenu = '1';
			var label = btn.textContent.trim() || 'Menu';
			function set(open) {
				cell.classList.toggle('open', open);
				btn.setAttribute('aria-expanded', String(open));
				btn.textContent = open ? 'Close' : label;
			}
			set(false);
			btn.addEventListener('click', function () { set(!cell.classList.contains('open')); });
			cell.addEventListener('keydown', function (e) {
				if (e.key === 'Escape' && cell.classList.contains('open')) { set(false); btn.focus(); }
			});
			cell.querySelectorAll('.ss-nav a').forEach(function (a) {
				a.addEventListener('click', function () { set(false); });
			});
		});
	}

	// ---- Toasts ----
	function toasts() {
		var box = document.querySelector('.ss-toasts');
		if (!box) {
			box = document.createElement('div');
			box.className = 'ss-toasts';
			box.setAttribute('role', 'status');
			box.setAttribute('aria-live', 'polite');
			// In the top layer (where supported) so toasts show above an open dialog's backdrop.
			if (typeof box.showPopover === 'function') box.popover = 'manual';
			document.body.appendChild(box);
		}
		// Keep it in the top layer; if a dialog opened after it, re-show it so it sits above that
		// dialog (only then, since re-showing replays the fade-in of the toasts already showing).
		if (box.popover) {
			try {
				var open = box.matches(':popover-open');
				if (open && document.querySelector('dialog[open]')) { box.hidePopover(); open = false; }
				if (!open) box.showPopover();
			} catch (e) { /* not supported */ }
		}
		return box;
	}
	window.ssToast = function (text, opts) {
		opts = opts || {};
		var t = document.createElement('div');
		t.className = 'ss-toast' + (opts.error ? ' ss-toast-error' : '');
		t.textContent = text;
		var box = toasts();
		box.appendChild(t);
		while (box.children.length > 3) box.removeChild(box.firstChild);
		var gone = false;
		function close() {
			if (gone) return;
			gone = true;
			t.classList.add('ss-toast-out');
			setTimeout(function () { t.remove(); }, 220);
		}
		setTimeout(close, opts.timeout || (opts.error ? 6000 : 3200));
		t.addEventListener('click', close);
		return close;
	};

	// ---- Confirm dialog: a cell like the others; resolves true for OK, false otherwise ----
	window.ssConfirm = function (message, opts) {
		opts = opts || {};
		if (typeof HTMLDialogElement !== 'function') return Promise.resolve(window.confirm(message));
		return new Promise(function (resolve) {
			var d = document.createElement('dialog');
			d.className = 'ss-cell ss-dialog' + (opts.cell ? ' ' + opts.cell : '');
			var band = document.createElement('div');
			band.className = 'ss-band';
			band.textContent = opts.title || 'Are you sure?';
			var p = document.createElement('p');
			p.textContent = message;
			var row = document.createElement('div');
			row.className = 'ss-dialog-actions';
			var cancel = document.createElement('button');
			cancel.type = 'button';
			cancel.className = 'ss-btn';
			cancel.textContent = opts.cancel || 'Cancel';
			var ok = document.createElement('button');
			ok.type = 'button';
			ok.className = 'ss-btn ss-btn-primary';
			ok.textContent = opts.ok || 'OK';
			row.append(cancel, ok);
			d.append(band, p, row);
			document.body.appendChild(d);
			var answer = false;
			cancel.addEventListener('click', function () { d.close(); });
			ok.addEventListener('click', function () { answer = true; d.close(); });
			d.addEventListener('click', function (e) { if (e.target === d) d.close(); }); // backdrop
			d.addEventListener('close', function () { d.remove(); resolve(answer); });
			d.showModal();
			ok.focus();
		});
	};

	if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', setupMenus);
	else setupMenus();
})();
