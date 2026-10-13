/*
 * Sign-in / register modals.
 *
 * - Forms marked [data-auth-form] submit in the background. The server
 *   answers {redirect} on success or {html} (the re-rendered form with its
 *   errors) on failure, so the modal stays open and shows what went wrong.
 * - Links marked [data-auth-required] open the sign-in modal and return the
 *   visitor to that link's page after signing in.
 * - /#login and /#register open the matching modal on load.
 */
(function () {
    "use strict";

    const loginModal = document.getElementById("loginModal");
    const registerModal = document.getElementById("registerModal");
    if (!loginModal || !window.bootstrap) return;

    const show = (el) => bootstrap.Modal.getOrCreateInstance(el).show();

    function setBusy(form, busy) {
        const button = form.querySelector('button[type="submit"]');
        if (!button) return;
        button.disabled = busy;
        button.querySelector(".spinner-border")?.classList.toggle("d-none", !busy);
    }

    function focusFirstField(container) {
        const field = container.querySelector(".is-invalid") ||
            container.querySelector("input:not([type=hidden])");
        field?.focus();
    }

    document.addEventListener("submit", async (event) => {
        const form = event.target.closest("form[data-auth-form]");
        if (!form) return;
        event.preventDefault();
        setBusy(form, true);

        try {
            const response = await fetch(form.action, {
                method: "POST",
                body: new FormData(form),
                headers: { "X-Requested-With": "XMLHttpRequest", Accept: "application/json" },
                credentials: "same-origin",
            });
            const data = await response.json();

            if (data.redirect) {
                window.location.assign(data.redirect);
                return;
            }
            if (data.html) {
                const body = form.closest("[data-auth-body]");
                body.innerHTML = data.html;
                focusFirstField(body);
                return;
            }
            throw new Error("Unexpected response");
        } catch (error) {
            // Anything unexpected: fall back to a normal page submit.
            form.removeAttribute("data-auth-form");
            form.submit();
        }
    });

    // Protected links and searches: sign in first, then continue there.
    function signInThenGo(target) {
        const next = loginModal.querySelector('input[name="next"]');
        if (next) next.value = target;
        show(loginModal);
    }

    document.addEventListener("click", (event) => {
        const link = event.target.closest("a[data-auth-required]");
        if (!link) return;
        event.preventDefault();
        signInThenGo(link.getAttribute("href"));
    });

    document.addEventListener("submit", (event) => {
        const form = event.target.closest("form[data-auth-required]");
        if (!form) return;
        event.preventDefault();
        const query = new URLSearchParams(new FormData(form)).toString();
        const action = new URL(form.action, location.href).pathname;
        signInThenGo(query ? `${action}?${query}` : action);
    });

    // Focus the first field once a modal is visible.
    [loginModal, registerModal].forEach((modal) => {
        modal?.addEventListener("shown.bs.modal", () => focusFirstField(modal));
    });

    if (location.hash === "#login") show(loginModal);
    if (location.hash === "#register" && registerModal) show(registerModal);
})();
