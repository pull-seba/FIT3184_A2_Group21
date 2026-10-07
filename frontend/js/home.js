import { requireAuth, signOut } from "./auth.js";
import { $ } from "./ui.js";

const claims = await requireAuth();
if (claims) {
  $("#first-name").textContent = claims.given_name;
  $("#user-name").textContent = `${claims.given_name} ${claims.family_name}`;
  $("#user-email").textContent = claims.email;
  document.body.classList.remove("pending");
}

$("#sign-out").addEventListener("click", async () => {
  await signOut();
  window.location.replace("login.html");
});
