/* Item report photo drop zone: click or drag a photo, preview it, check size. */
(function () {
    "use strict";

    const MAX_BYTES = 5 * 1024 * 1024;
    const zone = document.querySelector("[data-dropzone]");
    if (!zone) return;

    const input = zone.querySelector("[data-dropzone-input]");
    const area = zone.querySelector("[data-dropzone-area]");
    const preview = zone.querySelector("[data-dropzone-preview]");
    const empty = zone.querySelector("[data-dropzone-empty]");
    const name = zone.querySelector("[data-dropzone-name]");
    const error = zone.querySelector("[data-dropzone-error]");
    const clear = zone.querySelector('input[type="checkbox"]');

    function showError(message) {
        error.textContent = message;
        zone.classList.toggle("lf-field-invalid", Boolean(message));
    }

    function show(file) {
        if (!file) return;
        if (!file.type.startsWith("image/")) {
            input.value = "";
            showError("Please choose an image file.");
            return;
        }
        if (file.size > MAX_BYTES) {
            input.value = "";
            showError("That photo is larger than 5 MB. Please choose a smaller one.");
            return;
        }
        showError("");
        if (preview.src.startsWith("blob:")) URL.revokeObjectURL(preview.src);
        preview.src = URL.createObjectURL(file);
        preview.hidden = false;
        empty.hidden = true;
        name.textContent = `${file.name} · ${(file.size / 1024 / 1024).toFixed(1)} MB`;
        if (clear) clear.checked = false;
    }

    input.addEventListener("change", () => show(input.files[0]));

    ["dragenter", "dragover"].forEach((type) =>
        area.addEventListener(type, (event) => {
            event.preventDefault();
            area.classList.add("is-dragging");
        })
    );
    ["dragleave", "drop"].forEach((type) =>
        area.addEventListener(type, () => area.classList.remove("is-dragging"))
    );
    area.addEventListener("drop", (event) => {
        event.preventDefault();
        const file = event.dataTransfer.files[0];
        if (!file) return;
        const transfer = new DataTransfer();
        transfer.items.add(file);
        input.files = transfer.files;
        show(file);
    });
})();

/* AI category suggestion: asks the category model while the title and
   description are typed, and offers a one-click "Use" button. */
(function () {
    "use strict";

    const hint = document.querySelector("[data-category-hint]");
    if (!hint) return;

    const title = document.getElementById(hint.dataset.title);
    const description = document.getElementById(hint.dataset.description);
    const category = document.getElementById(hint.dataset.category);
    if (!title || !description || !category) return;

    let timer = null;
    let lastQuery = "";

    function clear() {
        hint.replaceChildren();
    }

    function show(data) {
        if (!data.category) return clear();
        const percent = Math.round(data.confidence * 100);
        const alreadyChosen = category.value === String(data.category.id);

        const icon = document.createElement("i");
        icon.className = "bi bi-cpu text-primary me-1";
        icon.setAttribute("aria-hidden", "true");

        const text = document.createElement("span");
        text.className = "text-secondary";
        text.textContent = alreadyChosen
            ? `AI agrees: ${data.category.name} (${percent}%)`
            : `AI suggests: ${data.category.name} (${percent}%) `;

        const parts = [icon, text];
        if (!alreadyChosen) {
            const use = document.createElement("button");
            use.type = "button";
            use.className = "btn btn-link btn-sm p-0 align-baseline";
            use.textContent = "Use";
            use.addEventListener("click", () => {
                category.value = String(data.category.id);
                category.dispatchEvent(new Event("change", { bubbles: true }));
                show(data);
            });
            parts.push(use);
        }
        hint.replaceChildren(...parts);
    }

    async function ask() {
        const query = `${title.value.trim()}|${description.value.trim()}`;
        if (title.value.trim().length < 3) return clear();
        if (query === lastQuery) return;
        lastQuery = query;

        const url = new URL(hint.dataset.url, window.location.origin);
        url.searchParams.set("title", title.value.trim());
        url.searchParams.set("description", description.value.trim());
        try {
            const response = await fetch(url, {
                headers: { Accept: "application/json" },
                credentials: "same-origin",
            });
            if (!response.ok || response.redirected) return;
            show(await response.json());
        } catch (error) {
            clear();   // the hint is optional; the form works without it
        }
    }

    function schedule() {
        clearTimeout(timer);
        timer = setTimeout(ask, 450);
    }

    title.addEventListener("input", schedule);
    description.addEventListener("input", schedule);
    category.addEventListener("change", () => { lastQuery = ""; schedule(); });
    if (title.value.trim()) schedule();
})();
