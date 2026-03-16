document.addEventListener('alpine:init', () => {

    Alpine.store('app', {
        tab: 'playground',
        toast: null,
        toastTimer: null,
        serverOnline: true,

        showToast(msg, type = 'success') {
            this.toast = { msg, type };
            clearTimeout(this.toastTimer);
            this.toastTimer = setTimeout(() => this.toast = null, 3000);
        },

        async checkHealth() {
            try {
                const r = await fetch('/health');
                this.serverOnline = r.ok;
            } catch { this.serverOnline = false; }
        },

        init() {
            this.checkHealth();
            setInterval(() => this.checkHealth(), 30000);
        }
    });

    // ─── Playground ───

    Alpine.data('playground', () => ({
        config: null,
        text: '',
        summarize: true,
        speaker: '',
        language: '',
        instruct: '',
        speed: 1.0,
        voice: '',
        useClonedVoice: false,
        clonedVoices: [],
        loading: false,
        result: null,

        async init() {
            const r = await fetch('/api/config');
            this.config = await r.json();
            this.speaker = this.config.default_speaker;
            this.language = this.config.default_language;
            this.speed = this.config.default_speed;
            this.instruct = this.config.default_instruct;

            // Fetch cloned voices for the dropdown
            const vr = await fetch('/api/voices');
            const voices = await vr.json();
            this.clonedVoices = voices.cloned || [];
        },

        async generate() {
            if (!this.text.trim()) return;
            this.loading = true;
            this.result = null;

            const form = new FormData();
            form.append('text', this.text);
            form.append('summarize', this.summarize);
            form.append('language', this.language);
            form.append('instruct', this.instruct);
            form.append('speed', this.speed);

            if (this.useClonedVoice && this.voice) {
                form.append('voice', this.voice);
            } else {
                form.append('speaker', this.speaker);
            }

            try {
                const r = await fetch('/api/speak', { method: 'POST', body: form });
                if (!r.ok) throw new Error(await r.text());
                this.result = await r.json();
            } catch (e) {
                Alpine.store('app').showToast(e.message, 'error');
            } finally {
                this.loading = false;
            }
        },
    }));

    // ─── Voices ───

    Alpine.data('voices', () => ({
        preset: [],
        cloned: [],
        uploadName: '',
        uploadTranscript: '',
        uploadFile: null,
        uploadFileName: '',
        uploading: false,
        dragover: false,

        async init() { await this.load(); },

        async load() {
            const r = await fetch('/api/voices');
            const data = await r.json();
            this.preset = data.preset;
            this.cloned = data.cloned;
        },

        handleDrop(e) {
            this.dragover = false;
            const file = e.dataTransfer.files[0];
            if (file) { this.uploadFile = file; this.uploadFileName = file.name; }
        },

        handleFileSelect(e) {
            const file = e.target.files[0];
            if (file) { this.uploadFile = file; this.uploadFileName = file.name; }
        },

        async upload() {
            if (!this.uploadName || !this.uploadFile) return;
            this.uploading = true;

            const form = new FormData();
            form.append('name', this.uploadName);
            form.append('audio', this.uploadFile);
            if (this.uploadTranscript) form.append('transcript', this.uploadTranscript);

            try {
                const r = await fetch('/api/voices', { method: 'POST', body: form });
                if (!r.ok) {
                    const err = await r.json();
                    throw new Error(err.detail || 'Upload failed');
                }
                Alpine.store('app').showToast('Voice uploaded');
                this.uploadName = '';
                this.uploadTranscript = '';
                this.uploadFile = null;
                this.uploadFileName = '';
                await this.load();
            } catch (e) {
                Alpine.store('app').showToast(e.message, 'error');
            } finally {
                this.uploading = false;
            }
        },

        async deleteVoice(name) {
            if (!confirm(`Delete voice "${name}"?`)) return;
            try {
                const r = await fetch(`/api/voices/${name}`, { method: 'DELETE' });
                if (!r.ok) throw new Error((await r.json()).detail);
                Alpine.store('app').showToast('Voice deleted');
                await this.load();
            } catch (e) {
                Alpine.store('app').showToast(e.message, 'error');
            }
        },
    }));

    // ─── History ───

    Alpine.data('history', () => ({
        entries: [],
        loading: true,

        async init() { await this.load(); },

        async load() {
            this.loading = true;
            try {
                const r = await fetch('/api/history');
                this.entries = await r.json();
            } finally {
                this.loading = false;
            }
        },

        async deleteEntry(id) {
            try {
                await fetch(`/api/history/${id}`, { method: 'DELETE' });
                this.entries = this.entries.filter(e => e.id !== id);
            } catch (e) {
                Alpine.store('app').showToast(e.message, 'error');
            }
        },

        async clearAll() {
            if (!confirm('Clear all history?')) return;
            try {
                await fetch('/api/history', { method: 'DELETE' });
                this.entries = [];
                Alpine.store('app').showToast('History cleared');
            } catch (e) {
                Alpine.store('app').showToast(e.message, 'error');
            }
        },

        reuseSettings(entry) {
            Alpine.store('app').tab = 'playground';
            // Wait for tab switch, then set values
            this.$nextTick(() => {
                const pg = document.querySelector('[x-data="playground()"]');
                if (!pg) return;
                const scope = Alpine.$data(pg);
                scope.text = entry.text_input;
                scope.summarize = entry.summarized;
                scope.language = entry.language;
                scope.instruct = entry.instruct;
                scope.speed = entry.speed;
                if (entry.voice) {
                    scope.useClonedVoice = true;
                    scope.voice = entry.voice;
                } else {
                    scope.useClonedVoice = false;
                    scope.speaker = entry.speaker;
                }
            });
        },

        formatTime(id) {
            // id format: YYYYMMDD_HHMMSS_xxxx
            const m = id.match(/^(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})/);
            if (!m) return id;
            return `${m[1]}-${m[2]}-${m[3]} ${m[4]}:${m[5]}:${m[6]}`;
        },
    }));
});
