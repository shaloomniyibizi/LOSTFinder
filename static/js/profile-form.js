/* Profile form niceties: live photo preview and a character counter. */
(function () {
    "use strict";

    const input = document.querySelector('.lf-avatar-picker input[type="file"]');
    const preview = document.querySelector("[data-avatar-preview]");
    const label = document.querySelector("[data-avatar-label]");

    if (input && preview) {
        input.addEventListener("change", () => {
            const file = input.files && input.files[0];
            if (!file || !file.type.startsWith("image/")) return;

            const img = document.createElement("img");
            img.alt = "Selected profile photo";
            img.src = URL.createObjectURL(file);
            img.onload = () => URL.revokeObjectURL(img.src);
            preview.replaceChildren(img);
            if (label) label.textContent = file.name;
        });
    }

    document.querySelectorAll("[data-char-count-for]").forEach((counter) => {
        const field = document.getElementById(counter.dataset.charCountFor);
        if (!field) return;
        const max = Number(field.getAttribute("maxlength")) || 0;
        const update = () => {
            counter.textContent = max
                ? `${field.value.length} / ${max}`
                : `${field.value.length} characters`;
        };
        field.addEventListener("input", update);
        update();
    });
})();
