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
                const r = await fetch('/health', { headers: { 'X-Health-Check': '1' } });
                this.serverOnline = r.ok;
            } catch { this.serverOnline = false; }
        },

        init() {
            if (!Alpine.store('app')._healthStarted) {
                Alpine.store('app')._healthStarted = true;
                this.checkHealth();
                setInterval(() => this.checkHealth(), 120000);
            }
        }
    });

    // ─── Playground ───

    Alpine.data('playground', () => ({
        config: null,
        presets: [],
        selectedPreset: '',
        selectedVoice: '',
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
            const [configR, voicesR, presetsR] = await Promise.all([
                fetch('/api/config'),
                fetch('/api/voices'),
                fetch('/api/presets'),
            ]);
            this.config = await configR.json();
            const voices = await voicesR.json();
            this.clonedVoices = voices.cloned || [];
            this.presets = await presetsR.json();

            this.speaker = this.config.default_speaker;
            this.selectedVoice = 'speaker:' + this.config.default_speaker;
            this.language = this.config.default_language;
            this.speed = this.config.default_speed;
            this.instruct = this.config.default_instruct;
        },

        onVoiceChange() {
            const v = this.selectedVoice;
            if (v.startsWith('voice:')) {
                this.useClonedVoice = true;
                this.voice = v.slice(6);
                this.speaker = '';
            } else {
                this.useClonedVoice = false;
                this.voice = '';
                this.speaker = v.slice(8); // 'speaker:'.length
            }
        },

        loadPreset() {
            if (!this.selectedPreset) return;
            const p = this.presets.find(x => x.name === this.selectedPreset);
            if (!p) return;
            this.language = p.language || 'English';
            this.instruct = p.instruct || '';
            this.speed = p.speed ?? 1.0;
            this.summarize = p.summarize ?? true;
            if (p.voice) {
                this.selectedVoice = 'voice:' + p.voice;
            } else {
                this.selectedVoice = 'speaker:' + (p.speaker || this.config.default_speaker);
            }
            this.onVoiceChange();
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

            if (this.selectedPreset) {
                form.append('preset', this.selectedPreset);
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

    // ─── Presets ───

    Alpine.data('presets', () => ({
        presets: [],
        editing: null, // preset being edited, or fresh object for new
        clonedVoices: [],
        speakers: [],

        async init() {
            await this.load();
            const [configR, voicesR] = await Promise.all([
                fetch('/api/config'),
                fetch('/api/voices'),
            ]);
            const config = await configR.json();
            this.speakers = config.speakers;
            const voices = await voicesR.json();
            this.clonedVoices = voices.cloned || [];
        },

        async load() {
            const r = await fetch('/api/presets');
            this.presets = await r.json();
        },

        newPreset() {
            this.editing = {
                name: '',
                speaker: 'Aiden',
                voice: '',
                language: 'English',
                instruct: '',
                speed: 1.0,
                summarize: true,
                _useVoice: false,
                _isNew: true,
            };
        },

        editPreset(p) {
            this.editing = {
                ...p,
                voice: p.voice || '',
                speaker: p.speaker || '',
                _useVoice: !!p.voice,
                _isNew: false,
                _origName: p.name,
            };
        },

        cancelEdit() {
            this.editing = null;
        },

        async savePreset() {
            const e = this.editing;
            if (!e.name.trim()) {
                Alpine.store('app').showToast('Name is required', 'error');
                return;
            }
            const body = {
                name: e.name.trim(),
                speaker: e._useVoice ? null : (e.speaker || 'Aiden'),
                voice: e._useVoice ? (e.voice || null) : null,
                language: e.language || 'English',
                instruct: e.instruct || '',
                speed: e.speed ?? 1.0,
                summarize: e.summarize ?? true,
            };

            try {
                const r = await fetch('/api/presets', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(body),
                });
                if (!r.ok) throw new Error((await r.json()).detail);
                Alpine.store('app').showToast('Preset saved');
                this.editing = null;
                await this.load();
            } catch (e) {
                Alpine.store('app').showToast(e.message, 'error');
            }
        },

        async deletePreset(name) {
            if (!confirm(`Delete preset "${name}"?`)) return;
            try {
                const r = await fetch(`/api/presets/${encodeURIComponent(name)}`, { method: 'DELETE' });
                if (!r.ok) throw new Error((await r.json()).detail);
                Alpine.store('app').showToast('Preset deleted');
                await this.load();
            } catch (e) {
                Alpine.store('app').showToast(e.message, 'error');
            }
        },

        useInPlayground(p) {
            Alpine.store('app').tab = 'playground';
            this.$nextTick(() => {
                const pg = document.querySelector('[x-data="playground()"]');
                if (!pg) return;
                const scope = Alpine.$data(pg);
                scope.selectedPreset = p.name;
                scope.loadPreset();
            });
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
        presets: [],
        filterPreset: '',
        loading: true,

        async init() {
            const [_, presetsR] = await Promise.all([
                this.load(),
                fetch('/api/presets'),
            ]);
            this.presets = await presetsR.json();
        },

        async load() {
            this.loading = true;
            try {
                const r = await fetch('/api/history');
                this.entries = await r.json();
            } finally {
                this.loading = false;
            }
        },

        get filteredEntries() {
            if (!this.filterPreset) return this.entries;
            if (this.filterPreset === '__none__') return this.entries.filter(e => !e.preset);
            return this.entries.filter(e => e.preset === this.filterPreset);
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
            this.$nextTick(() => {
                const pg = document.querySelector('[x-data="playground()"]');
                if (!pg) return;
                const scope = Alpine.$data(pg);
                scope.text = entry.text_input;
                scope.summarize = entry.summarized;
                scope.language = entry.language;
                scope.instruct = entry.instruct;
                scope.speed = entry.speed;
                if (entry.preset) {
                    scope.selectedPreset = entry.preset;
                }
                if (entry.voice) {
                    scope.selectedVoice = 'voice:' + entry.voice;
                } else {
                    scope.selectedVoice = 'speaker:' + entry.speaker;
                }
                scope.onVoiceChange();
            });
        },

        formatTime(id) {
            const m = id.match(/^(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})/);
            if (!m) return id;
            return `${m[1]}-${m[2]}-${m[3]} ${m[4]}:${m[5]}:${m[6]}`;
        },
    }));
});
