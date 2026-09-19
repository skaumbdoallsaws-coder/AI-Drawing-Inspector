(function (root, factory) {
    const api = factory();
    if (typeof module === 'object' && module.exports) module.exports = api;
    if (root) root.InspectorProAssemblyKnowledgeReview = api;
}(typeof self !== 'undefined' ? self : this, function () {
    'use strict';

    function assetUrl(productId, packageId, relativePath) {
        const path = String(relativePath || '').split('/').filter(Boolean)
            .map(encodeURIComponent).join('/');
        return '/api/training/assembly-knowledge/'
            + encodeURIComponent(String(productId || '')) + '/'
            + encodeURIComponent(String(packageId || '')) + '/assets/' + path;
    }

    function reviewActionBody(review, item, action, actor, editedValue) {
        const identity = review && review.identity || {};
        const body = {
            baseRevision: String(identity.packageRevision || ''),
            sourceRevision: String(identity.sourceRevision || ''),
            claimId: String(item && item.claimId || ''),
            action: String(action || ''),
            actor: String(actor || ''),
        };
        if (action === 'edit') body.editedValue = editedValue;
        return body;
    }

    function formatValue(value) {
        if (value === null || value === undefined) return 'Unknown';
        if (typeof value === 'string') return value;
        if (typeof value === 'number' || typeof value === 'boolean') return String(value);
        return JSON.stringify(value, null, 2);
    }

    function normalizeReviewPayload(payload) {
        const review = payload && payload.review || payload || {};
        return {
            identity: review.identity || {},
            summary: review.summary || {},
            assets: review.assets || {},
            sourceStatus: review.sourceStatus || {},
            items: Array.isArray(review.items) ? review.items : [],
            findings: Array.isArray(review.findings) ? review.findings : [],
        };
    }

    function element(tag, className, text) {
        const node = document.createElement(tag);
        if (className) node.className = className;
        if (text !== undefined && text !== null) node.textContent = String(text);
        return node;
    }

    function namedButton(label, className, handler) {
        const button = element('button', className, label);
        button.type = 'button';
        button.addEventListener('click', handler);
        return button;
    }

    function AssemblyReviewViewer(host, options) {
        this.host = host;
        this.THREE = options.THREE;
        this.fetch = options.fetch;
        this.sceneRoot = null;
        this.meshes = [];
        this.frame = 0;
        this.resizeObserver = null;
        this.pointer = null;
        this.center = null;
        this.distance = 10;
        this.azimuth = 0.75;
        this.elevation = 0.55;
        this._build();
    }

    AssemblyReviewViewer.prototype._build = function () {
        const THREE = this.THREE;
        if (!THREE || typeof THREE.WebGLRenderer !== 'function') {
            this.host.appendChild(element(
                'div',
                'ak-review-viewer-message',
                'Interactive 3D is unavailable.'
            ));
            return;
        }
        this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
        this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
        this.renderer.outputEncoding = THREE.sRGBEncoding;
        this.canvas = this.renderer.domElement;
        this.canvas.className = 'ak-review-canvas';
        this.canvas.setAttribute('aria-label', 'Assembly evidence viewer');
        this.host.appendChild(this.canvas);
        this.scene = new THREE.Scene();
        this.camera = new THREE.PerspectiveCamera(42, 1, 0.01, 100000);
        this.center = new THREE.Vector3();
        this.scene.add(new THREE.HemisphereLight(0xffffff, 0x52606d, 1.45));
        const key = new THREE.DirectionalLight(0xffffff, 1.15);
        key.position.set(6, 8, 10);
        this.scene.add(key);
        const fill = new THREE.DirectionalLight(0x9fd7ff, 0.55);
        fill.position.set(-7, 3, -5);
        this.scene.add(fill);
        this._bindControls();
        this._resize();
        if (typeof ResizeObserver !== 'undefined') {
            this.resizeObserver = new ResizeObserver(this._resize.bind(this));
            this.resizeObserver.observe(this.host);
        }
        this._tick();
    };

    AssemblyReviewViewer.prototype._bindControls = function () {
        if (!this.canvas) return;
        this.canvas.addEventListener('pointerdown', function (event) {
            this.pointer = {
                id: event.pointerId,
                x: event.clientX,
                y: event.clientY,
                azimuth: this.azimuth,
                elevation: this.elevation,
            };
            this.canvas.setPointerCapture(event.pointerId);
        }.bind(this));
        this.canvas.addEventListener('pointermove', function (event) {
            if (!this.pointer || this.pointer.id !== event.pointerId) return;
            this.azimuth = this.pointer.azimuth
                - (event.clientX - this.pointer.x) * 0.008;
            this.elevation = Math.max(
                -1.35,
                Math.min(1.35, this.pointer.elevation
                    + (event.clientY - this.pointer.y) * 0.008)
            );
            this._updateCamera();
        }.bind(this));
        const release = function (event) {
            if (this.pointer && this.pointer.id === event.pointerId) this.pointer = null;
        }.bind(this);
        this.canvas.addEventListener('pointerup', release);
        this.canvas.addEventListener('pointercancel', release);
        this.canvas.addEventListener('wheel', function (event) {
            event.preventDefault();
            this.distance = Math.max(
                0.05,
                this.distance * Math.exp(event.deltaY * 0.001)
            );
            this._updateCamera();
        }.bind(this), { passive: false });
    };

    AssemblyReviewViewer.prototype._resize = function () {
        if (!this.renderer || !this.camera) return;
        const width = Math.max(1, this.host.clientWidth);
        const height = Math.max(1, this.host.clientHeight);
        this.renderer.setSize(width, height, false);
        this.camera.aspect = width / height;
        this.camera.updateProjectionMatrix();
    };

    AssemblyReviewViewer.prototype._tick = function () {
        if (!this.renderer || !this.scene || !this.camera) return;
        this.renderer.render(this.scene, this.camera);
        this.frame = window.requestAnimationFrame(this._tick.bind(this));
    };

    AssemblyReviewViewer.prototype._updateCamera = function () {
        if (!this.camera || !this.center) return;
        const horizontal = Math.cos(this.elevation) * this.distance;
        this.camera.position.set(
            this.center.x + Math.cos(this.azimuth) * horizontal,
            this.center.y + Math.sin(this.elevation) * this.distance,
            this.center.z + Math.sin(this.azimuth) * horizontal
        );
        this.camera.lookAt(this.center);
    };

    AssemblyReviewViewer.prototype._fitObjects = function (objects) {
        if (!this.THREE || !this.camera || !objects.length) return;
        const box = new this.THREE.Box3();
        objects.forEach(function (object) { box.expandByObject(object); });
        if (box.isEmpty()) return;
        const size = box.getSize(new this.THREE.Vector3());
        box.getCenter(this.center);
        const radius = Math.max(size.x, size.y, size.z, 0.01);
        this.distance = radius / Math.tan(this.camera.fov * Math.PI / 360) * 0.9;
        this.camera.near = Math.max(0.001, this.distance / 1000);
        this.camera.far = Math.max(100, this.distance * 50);
        this.camera.updateProjectionMatrix();
        this._updateCamera();
    };

    AssemblyReviewViewer.prototype.load = function (url) {
        if (!this.scene || !this.THREE || typeof this.THREE.GLTFLoader !== 'function') {
            return Promise.resolve(false);
        }
        if (this.sceneRoot) this.scene.remove(this.sceneRoot);
        this.meshes = [];
        return new Promise(function (resolve, reject) {
            const loader = new this.THREE.GLTFLoader();
            loader.load(url, function (gltf) {
                this.sceneRoot = gltf.scene;
                this.scene.add(this.sceneRoot);
                this.sceneRoot.traverse(function (object) {
                    if (!object.isMesh) return;
                    if (Array.isArray(object.material)) {
                        object.material = object.material.map(function (material) {
                            return material.clone();
                        });
                    } else if (object.material) {
                        object.material = object.material.clone();
                    }
                    this.meshes.push(object);
                }.bind(this));
                this._fitObjects([this.sceneRoot]);
                resolve(true);
            }.bind(this), undefined, reject);
        }.bind(this));
    };

    AssemblyReviewViewer.prototype.highlight = function (occurrences) {
        if (!this.THREE || !this.meshes.length) return;
        const names = new Set((occurrences || []).map(function (item) {
            return String(item && item.name || '').toLowerCase();
        }).filter(Boolean));
        const selected = [];
        this.meshes.forEach(function (mesh) {
            const materials = Array.isArray(mesh.material) ? mesh.material : [mesh.material];
            const isSelected = names.size === 0
                || names.has(String(mesh.name || '').toLowerCase());
            materials.filter(Boolean).forEach(function (material) {
                material.transparent = !isSelected;
                material.opacity = isSelected ? 1 : 0.09;
                material.depthWrite = isSelected;
                if (material.emissive) {
                    material.emissive.setHex(isSelected && names.size ? 0x137fb7 : 0x000000);
                    material.emissiveIntensity = isSelected && names.size ? 0.42 : 0;
                }
                material.needsUpdate = true;
            });
            if (isSelected) selected.push(mesh);
        });
        if (selected.length) this._fitObjects(selected);
    };

    AssemblyReviewViewer.prototype.dispose = function () {
        if (this.frame) window.cancelAnimationFrame(this.frame);
        if (this.resizeObserver) this.resizeObserver.disconnect();
        if (this.sceneRoot) {
            this.sceneRoot.traverse(function (object) {
                if (object.geometry && object.geometry.dispose) object.geometry.dispose();
                const materials = Array.isArray(object.material)
                    ? object.material : [object.material];
                materials.filter(Boolean).forEach(function (material) {
                    if (material.dispose) material.dispose();
                });
            });
        }
        if (this.renderer) this.renderer.dispose();
        this.host.textContent = '';
    };

    function ReviewSurface(options) {
        this.options = options || {};
        this.fetch = this.options.fetch || (
            typeof window !== 'undefined' ? window.fetch.bind(window) : null
        );
        this.THREE = this.options.THREE || (
            typeof window !== 'undefined' ? window.THREE : null
        );
        this.actor = this.options.actor || 'Local InspectorPro user';
        this.productId = '';
        this.packageId = '';
        this.review = normalizeReviewPayload({});
        this.index = 0;
        this.viewer = null;
        this.opened = false;
        this.busy = false;
        this._keyHandler = this._onKey.bind(this);
    }

    ReviewSurface.prototype._request = async function (url, options) {
        const response = await this.fetch(url, options);
        const payload = await response.json().catch(function () { return {}; });
        if (!response.ok) {
            const detail = payload.detail;
            throw new Error(
                typeof detail === 'string'
                    ? detail
                    : (payload.error || 'Assembly knowledge request failed')
            );
        }
        return payload;
    };

    ReviewSurface.prototype._build = function () {
        if (this.backdrop) return;
        this.backdrop = element('div', 'ak-review-backdrop');
        this.backdrop.hidden = true;
        this.shell = element('section', 'ak-review-shell');
        this.shell.setAttribute('role', 'dialog');
        this.shell.setAttribute('aria-modal', 'true');
        this.shell.setAttribute('aria-label', 'Assembly knowledge review');

        const header = element('header', 'ak-review-header');
        const heading = element('div', 'ak-review-heading');
        this.title = element('h2', '', 'Assembly Knowledge Review');
        this.identity = element('p', 'ak-review-identity', '');
        heading.appendChild(this.title);
        heading.appendChild(this.identity);
        this.closeButton = namedButton('Close', 'ak-review-close', this.close.bind(this));
        header.appendChild(heading);
        header.appendChild(this.closeButton);

        const body = element('div', 'ak-review-body');
        const visual = element('div', 'ak-review-visual');
        this.viewerHost = element('div', 'ak-review-viewer');
        this.visualStatus = element('div', 'ak-review-visual-status', 'Loading assembly...');
        this.presentationImage = element('img', 'ak-review-presentation');
        this.presentationImage.alt = '';
        this.presentationImage.hidden = true;
        visual.appendChild(this.viewerHost);
        visual.appendChild(this.presentationImage);
        visual.appendChild(this.visualStatus);

        this.details = element('aside', 'ak-review-details');
        body.appendChild(visual);
        body.appendChild(this.details);

        const footer = element('footer', 'ak-review-footer');
        this.progress = element('div', 'ak-review-progress');
        const navigation = element('div', 'ak-review-navigation');
        this.previousButton = namedButton(
            'Previous',
            'ak-review-secondary',
            this.previous.bind(this)
        );
        this.nextButton = namedButton('Next', 'ak-review-secondary', this.next.bind(this));
        navigation.appendChild(this.previousButton);
        navigation.appendChild(this.nextButton);
        footer.appendChild(this.progress);
        footer.appendChild(navigation);

        this.shell.appendChild(header);
        this.shell.appendChild(body);
        this.shell.appendChild(footer);
        this.backdrop.appendChild(this.shell);
        this.backdrop.addEventListener('pointerdown', function (event) {
            if (event.target === this.backdrop) this.close();
        }.bind(this));
        document.body.appendChild(this.backdrop);
    };

    ReviewSurface.prototype.open = async function (productId, packageId) {
        if (!this.fetch) throw new Error('Fetch is unavailable.');
        this._build();
        this.productId = String(productId || '');
        if (!this.productId) throw new Error('A product ID is required.');
        this.backdrop.hidden = false;
        this.opened = true;
        document.addEventListener('keydown', this._keyHandler);
        document.documentElement.classList.add('ak-review-open');
        this.closeButton.focus();
        try {
            if (packageId) {
                this.packageId = String(packageId);
            } else {
                const listing = await this._request(
                    '/api/training/assembly-knowledge/' + encodeURIComponent(this.productId),
                    { cache: 'no-store' }
                );
                const packages = Array.isArray(listing.packages) ? listing.packages : [];
                if (!packages.length) throw new Error(
                    'No prepared assembly knowledge package is available.'
                );
                packages.sort(function (left, right) {
                    return Number(right.pendingReviewCount || 0)
                        - Number(left.pendingReviewCount || 0);
                });
                this.packageId = String(packages[0].packageId);
            }
            await this.reload();
            return true;
        } catch (error) {
            this._renderError(error);
            return false;
        }
    };

    ReviewSurface.prototype.reload = async function () {
        const payload = await this._request(
            '/api/training/assembly-knowledge/'
                + encodeURIComponent(this.productId) + '/'
                + encodeURIComponent(this.packageId) + '/review',
            { cache: 'no-store' }
        );
        this.review = normalizeReviewPayload(payload);
        this.index = Math.min(this.index, Math.max(0, this.review.items.length - 1));
        this._render();
        await this._loadViewer();
    };

    ReviewSurface.prototype._loadViewer = async function () {
        const relative = this.review.assets.assemblyModel;
        if (!relative || !this.opened) {
            this.visualStatus.textContent = 'No interactive assembly model is registered.';
            return;
        }
        if (!this.viewer) {
            this.viewer = new AssemblyReviewViewer(this.viewerHost, {
                THREE: this.THREE,
                fetch: this.fetch,
            });
        }
        this.visualStatus.textContent = 'Loading interactive assembly...';
        try {
            await this.viewer.load(assetUrl(this.productId, this.packageId, relative));
            this.visualStatus.textContent = 'Drag to rotate. Scroll to zoom.';
            this._syncVisualContext();
        } catch (error) {
            this.visualStatus.textContent = 'Interactive model could not be loaded.';
            this._showPresentation();
        }
    };

    ReviewSurface.prototype._showPresentation = function () {
        const item = this.review.items[this.index];
        const relevant = item && item.visualContext
            && item.visualContext.views && item.visualContext.views[0];
        const fallback = this.review.assets.presentationViews
            && this.review.assets.presentationViews[0];
        const view = relevant || fallback;
        if (!view || !view.assetPath) return;
        this.presentationImage.src = assetUrl(
            this.productId,
            this.packageId,
            view.assetPath
        );
        this.presentationImage.hidden = false;
    };

    ReviewSurface.prototype._syncVisualContext = function () {
        const item = this.review.items[this.index];
        const occurrences = item && item.visualContext
            && item.visualContext.occurrences || [];
        if (this.viewer) this.viewer.highlight(occurrences);
        this.presentationImage.hidden = true;
    };

    ReviewSurface.prototype._render = function () {
        const identity = this.review.identity;
        this.identity.textContent = String(identity.readiness || 'unknown')
            + ' | revision ' + String(identity.packageRevision || '').slice(0, 12)
            + ' | CAD source: ' + (this.review.sourceStatus.current ? 'current' : 'unverified')
            + ' | production eligible: ' + (identity.productionEligible ? 'yes' : 'no');
        const item = this.review.items[this.index];
        this.details.textContent = '';
        if (!item) {
            const empty = element('div', 'ak-review-empty');
            empty.appendChild(element('h3', '', 'No prioritized claims remain'));
            empty.appendChild(element(
                'p',
                '',
                'The package can remain planning-ready without converting inferred '
                    + 'claims into production-approved requirements.'
            ));
            this.details.appendChild(empty);
            this.progress.textContent = '0 pending claims';
            this.previousButton.disabled = true;
            this.nextButton.disabled = true;
            return;
        }
        const top = element('div', 'ak-review-item-heading');
        const badges = element('div', 'ak-review-badges');
        [
            item.knowledgeStatus,
            item.authority,
            item.reviewStatus,
        ].filter(Boolean).forEach(function (value) {
            badges.appendChild(element('span', 'ak-review-badge', value));
        });
        top.appendChild(element(
            'div',
            'ak-review-kicker',
            String(item.predicate || '').replace(/_/g, ' ')
        ));
        top.appendChild(element('h3', '', formatValue(item.value)));
        top.appendChild(badges);
        this.details.appendChild(top);
        this.details.appendChild(element(
            'p',
            'ak-review-why',
            item.whyItMatters || 'Affects process-planning context.'
        ));

        const entities = element('section', 'ak-review-section');
        entities.appendChild(element('h4', '', 'CAD context'));
        (item.entities || []).forEach(function (entity) {
            const row = element('div', 'ak-review-evidence-row');
            row.appendChild(element(
                'strong',
                '',
                entity.name || entity.ref
            ));
            row.appendChild(element(
                'span',
                '',
                entity.kind + ' | ' + entity.ref
            ));
            entities.appendChild(row);
        });
        this.details.appendChild(entities);

        const evidence = element('section', 'ak-review-section');
        evidence.appendChild(element('h4', '', 'Evidence'));
        if (!(item.evidence || []).length) {
            evidence.appendChild(element(
                'p',
                'ak-review-muted',
                'No authoritative manufacturing source is attached.'
            ));
        }
        (item.evidence || []).forEach(function (source) {
            const row = element('div', 'ak-review-evidence-row');
            row.appendChild(element(
                'strong',
                '',
                source.sourceType || source.kind || 'Evidence'
            ));
            row.appendChild(element(
                'span',
                '',
                source.description || source.evidenceId || ''
            ));
            evidence.appendChild(row);
        });
        this.details.appendChild(evidence);

        const actions = element('div', 'ak-review-actions');
        [
            ['Confirm', 'confirm', 'primary'],
            ['Edit', 'edit', ''],
            ['Reject', 'reject', 'danger'],
            ['Mark unknown', 'mark_unknown', ''],
            ['Defer', 'defer', ''],
        ].forEach(function (definition) {
            const button = namedButton(
                definition[0],
                'ak-review-action ' + definition[2],
                this.applyAction.bind(this, definition[1])
            );
            button.disabled = this.busy;
            actions.appendChild(button);
        }, this);
        this.details.appendChild(actions);
        this.progress.textContent = (this.index + 1) + ' of '
            + this.review.items.length + ' pending claims';
        this.previousButton.disabled = this.busy || this.index <= 0;
        this.nextButton.disabled = this.busy
            || this.index >= this.review.items.length - 1;
        this._syncVisualContext();
    };

    ReviewSurface.prototype.applyAction = async function (action) {
        const item = this.review.items[this.index];
        if (!item || this.busy) return false;
        let editedValue;
        if (action === 'edit') {
            const replacement = window.prompt(
                'Edit the proposed value as JSON or plain text:',
                formatValue(item.value)
            );
            if (replacement === null) return false;
            try {
                editedValue = JSON.parse(replacement);
            } catch (_error) {
                editedValue = replacement;
            }
        }
        this.busy = true;
        this._render();
        try {
            const payload = await this._request(
                '/api/training/assembly-knowledge/'
                    + encodeURIComponent(this.productId) + '/'
                    + encodeURIComponent(this.packageId) + '/review-actions',
                {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(reviewActionBody(
                        this.review,
                        item,
                        action,
                        this.actor,
                        editedValue
                    )),
                }
            );
            this.review = normalizeReviewPayload(payload);
            this.index = Math.min(this.index, Math.max(0, this.review.items.length - 1));
            this.busy = false;
            this._render();
            return true;
        } catch (error) {
            this.busy = false;
            this._renderError(error);
            return false;
        }
    };

    ReviewSurface.prototype._renderError = function (error) {
        this.details.textContent = '';
        const box = element('div', 'ak-review-error');
        box.appendChild(element('h3', '', 'Review unavailable'));
        box.appendChild(element('p', '', error && error.message || String(error)));
        box.appendChild(namedButton(
            'Retry',
            'ak-review-action primary',
            this.reload.bind(this)
        ));
        this.details.appendChild(box);
    };

    ReviewSurface.prototype.previous = function () {
        if (this.index <= 0) return;
        this.index -= 1;
        this._render();
    };

    ReviewSurface.prototype.next = function () {
        if (this.index >= this.review.items.length - 1) return;
        this.index += 1;
        this._render();
    };

    ReviewSurface.prototype._onKey = function (event) {
        if (!this.opened) return;
        if (event.key === 'Escape') {
            event.preventDefault();
            this.close();
        }
    };

    ReviewSurface.prototype.close = function () {
        if (!this.opened) return;
        this.opened = false;
        document.removeEventListener('keydown', this._keyHandler);
        document.documentElement.classList.remove('ak-review-open');
        if (this.viewer) {
            this.viewer.dispose();
            this.viewer = null;
        }
        if (this.backdrop) this.backdrop.hidden = true;
        if (typeof this.options.onClose === 'function') this.options.onClose();
    };

    ReviewSurface.prototype.destroy = function () {
        this.close();
        if (this.backdrop && this.backdrop.parentNode) {
            this.backdrop.parentNode.removeChild(this.backdrop);
        }
        this.backdrop = null;
    };

    return {
        assetUrl: assetUrl,
        normalizeReviewPayload: normalizeReviewPayload,
        reviewActionBody: reviewActionBody,
        create: function (options) { return new ReviewSurface(options); },
    };
}));
