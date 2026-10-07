export const $ = (selector) => document.querySelector(selector);

export function showMessage(text, type = "error") {
  const box = $("#message");
  box.textContent = text;
  box.className = `message ${type}`;
  box.hidden = !text;
}

export function show(sectionId) {
  document.querySelectorAll("section[data-step]").forEach((s) => (s.hidden = s.id !== sectionId));
  showMessage("");
}

// Disables the form's button while a request is in flight and reports errors.
export function handleSubmit(form, action) {
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = form.querySelector("button[type=submit]");
    button.disabled = true;
    try {
      await action(new FormData(form));
    } catch (err) {
      showMessage(err.message || String(err));
    } finally {
      button.disabled = false;
    }
  });
}

export function passwordsMatch(data, a = "password", b = "confirm") {
  if (data.get(a) !== data.get(b)) throw new Error("Passwords do not match.");
}
