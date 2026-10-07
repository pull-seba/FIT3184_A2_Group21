import { signIn, currentUser } from "./auth.js";
import { $, show, showMessage, handleSubmit, passwordsMatch } from "./ui.js";

if (await currentUser()) window.location.replace("index.html");

const params = new URLSearchParams(window.location.search);
if (params.get("verified")) showMessage("Email verified - you can now sign in.", "success");
if (params.get("reset")) showMessage("Password changed - sign in with your new password.", "success");

let pendingChallenge = null;

handleSubmit($("#login-form"), async (data) => {
  const email = data.get("email").trim();
  let result;
  try {
    result = await signIn(email, data.get("password"));
  } catch (err) {
    if (err.code === "UserNotConfirmedException") {
      return window.location.replace(`signup.html?verify=${encodeURIComponent(email)}`);
    }
    throw err;
  }
  if (result.status === "SIGNED_IN") return window.location.replace("index.html");

  // Invited user signing in with a temporary password.
  pendingChallenge = result;
  for (const label of document.querySelectorAll("[data-attr]")) {
    const required = result.requiredAttributes.includes(label.dataset.attr);
    label.hidden = !required;
    label.querySelector("input").required = required;
  }
  show("new-password");
});

handleSubmit($("#new-password-form"), async (data) => {
  passwordsMatch(data);
  const attributes = {};
  for (const name of pendingChallenge.requiredAttributes) {
    if (data.get(name)) attributes[name] = data.get(name).trim();
  }
  await pendingChallenge.completeNewPassword(data.get("password"), attributes);
  window.location.replace("index.html");
});
