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
