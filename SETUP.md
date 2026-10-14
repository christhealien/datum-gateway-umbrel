# Setup guide: from the archives to a running app

Three repos, same layout on Gitea (testing) and GitHub (public):

| Repo | Holds |
|---|---|
| `blake2b` | The Umbrel **store**: both app folders. This is the URL people add. |
| `blake2b-asic-control` | Source of the ASIC app (you already have it). |
| `datum-gateway-umbrel` | Source of the DATUM app (this repo). |

Replace these in every command:

* `GITEA` = your Gitea address, e.g. `http://192.168.1.50:3000`
* `GUSER` = your Gitea user name
* `UMBREL` = your Umbrel's address, e.g. `umbrel.local`

What was **not** tested here (no Docker, no Umbrel, no C compiler in the build environment): the Docker build, running on an
Umbrel, and whether umbrelOS accepts a Gitea address as a community store. Everything else (UI, sign-in proxy, setup, restart,
patch scripts, sync and retarget scripts, workflows' syntax) was run or checked. Step 14 tells you what to look at first.

---

## Part A: on your Linux PC, once

**1. Tools**
```
sudo apt update && sudo apt install -y git python3 curl
```
Docker is only needed if you want to build the image on your own PC (optional, step 17).

**2. Unpack the two archives** (the files you were sent)
```
mkdir -p ~/umbrel-work && cd ~/umbrel-work
tar xzf ~/Downloads/datum-gateway-umbrel.tar.gz
tar xzf ~/Downloads/blake2b-store.tar.gz
ls
```
You now have `datum-gateway-umbrel/` and `blake2b-store/`.

**3. Git identity** (skip if already set)
```
git config --global user.name "christhealien"
git config --global user.email "you@example.com"
```

---

## Part B: test on your Gitea first

**4. Create three empty repos in Gitea** (web page → **+** → New Repository; no README, no .gitignore):
`datum-gateway-umbrel`, `blake2b`, and (optional mirror) `blake2b-asic-control`.

**5. Create two access tokens** in Gitea (avatar → Settings → Applications → Generate New Token):
* `registry` with permission **write:package**
* `repo` with permission **write:repository**

**6. Turn on Actions and add a runner** (only if you want Gitea to build the image itself; otherwise use step 17).
Repo → Settings → Actions must be enabled, and a runner (`act_runner`) with Docker must be registered to your Gitea
(Gitea docs: "Act Runner"). Then in the `datum-gateway-umbrel` repo → Settings → Actions → Secrets add:
* `REGISTRY_TOKEN` = the `registry` token
* `REPO_TOKEN` = the `repo` token

**7. Push the source repo to Gitea**
```
cd ~/umbrel-work/datum-gateway-umbrel
git init -b master
git add -A
git commit -m "DATUM Gateway for Umbrel"
git remote add gitea GITEA/GUSER/datum-gateway-umbrel.git
git push -u gitea master
```
(Gitea asks for your user name and a password or token.)

**8. Fill the Gitea test store.** The files in the source repo point at GitHub; this rewrites only the copy that goes
into the store so it points at your Gitea:
```
cd ~/umbrel-work/blake2b-store
git init -b master
git add -A
git commit -m "Store with Blake2b ASIC Control"
git remote add gitea GITEA/GUSER/blake2b.git
cd ~/umbrel-work/datum-gateway-umbrel
RETARGET_ARGS="gitea --url GITEA --owner GUSER" tools/publish_to_store.sh ~/umbrel-work/blake2b-store gitea master
```

**9. If your Gitea is plain HTTP, let Docker (on the runner PC) use it as a registry.**
Edit `/etc/docker/daemon.json` on the machine running the runner:
```
{ "insecure-registries": ["192.168.1.50:3000"] }
```
(use your Gitea host:port), then `sudo systemctl restart docker`. Do the same on the **Umbrel** later (step 12) because Umbrel
pulls the image from there.

**10. Build the image by tagging a release**
```
cd ~/umbrel-work/datum-gateway-umbrel
git tag datum-v1.0.0
git push gitea datum-v1.0.0
```
Watch it in Gitea → the repo → Actions. When it is green the image `GITEA_HOST:PORT/GUSER/blake2b-datum-gateway:1.0.0`
exists under your profile → Packages, and the workflow has refreshed the store repo `blake2b`.
(If the store was filled by step 8 already, that is fine; the workflow only changes it when something differs.)

**11. Add the test store on Umbrel**: App Store → **⋯** (top right) → **Community App Stores** → paste
`GITEA/GUSER/blake2b` → Add. Umbrel lists the apps.
*Unverified:* some umbrelOS versions only accept GitHub addresses there. If the box refuses your Gitea address, go to step 14.

**12. Let the Umbrel pull from your HTTP Gitea registry.** SSH in (`ssh umbrel@UMBREL`, password = your Umbrel password):
```
sudo mkdir -p /etc/docker
echo '{ "insecure-registries": ["192.168.1.50:3000"] }' | sudo tee /etc/docker/daemon.json
sudo systemctl restart docker
```
If the Gitea package is private also run `sudo docker login 192.168.1.50:3000 -u GUSER` (use the `registry` token as password), or set the package public
in Gitea (Packages → the package → Settings).

**13. Install DATUM Gateway (blake2b)** from the test store (the Bitcoin app, Knots or Core, must be installed and running).
Open it, sign in with the username and password Umbrel shows on the app's page, enter your reward address on the setup page,
then point your miners at `stratum+tcp://UMBREL:23334`.

**14. If something does not work, look here first**
```
sudo docker ps -a | grep datum                                  # is it running or restarting?
sudo docker logs --tail 100 blake2b-datum-gateway_web_1        # what it says
sudo docker logs -f blake2b-datum-gateway_web_1                # follow
sudo docker restart blake2b-datum-gateway_web_1                # restart the container
```
* "waiting for node": the Bitcoin app is still syncing or not started; the page says which.
* Forgot the login: `sudo rm ~/umbrel/app-data/blake2b-datum-gateway/data/auth.json && sudo docker restart blake2b-datum-gateway_web_1` (back to the login Umbrel shows).
* Image pull errors: step 9/12 (insecure registry) or the package is private.
* Store refused: use the fallback in step 15.

**15. Fallback if Umbrel will not take a Gitea store address:** create an empty **public** GitHub repo `blake2b-test`, push the Gitea store
copy there (`git remote add gh https://github.com/christhealien/blake2b-test.git && git push gh master` from `~/umbrel-work/blake2b-store`),
and add `https://github.com/christhealien/blake2b-test` as the store. The app's image still comes from Gitea (step 12).

**16. Installed app does not change when the store address changes.** If you earlier installed Blake2b ASIC Control from its
own repo-as-store, installing the same id from this store may collide; remove the old store (Community App Stores → remove) and
reinstall (the app's data folder survives an uninstall only if you choose to keep it, so export your miners first).

**17. (Optional) Build and try the image on your own PC instead of Gitea Actions**
```
cd ~/umbrel-work/datum-gateway-umbrel/datum-app
docker build --build-arg VERSION=1.0.0 -t blake2b-datum-gateway:test .
docker run --rm -p 7152:7152 -p 23334:23334 -e APP_PASSWORD=changeme1 -v $PWD/../_testdata:/data blake2b-datum-gateway:test
```
Open http://localhost:7152, sign in as `umbrel` / `changeme1`. Without a node it shows "waiting for node" after setup; that is expected.
The build log prints `Building upstream vX.Y.Z` and the two patch lines (`best_share: ...added`, `fast_notify: ...250 ms`).

---

## Part C: release publicly on GitHub

**18. Create the repos on GitHub** (needs the GitHub CLI: `sudo apt install -y gh`, then `gh auth login`)
```
gh repo create christhealien/datum-gateway-umbrel --public
gh repo create christhealien/blake2b --public
```
(`blake2b-asic-control` already exists.)

**19. Push the DATUM source repo**
```
cd ~/umbrel-work/datum-gateway-umbrel
git remote add github https://github.com/christhealien/datum-gateway-umbrel.git
git push -u github master
```

**20. Build the public image.** The GitHub workflow runs on a `datum-v*` tag:
```
git tag datum-v1.0.0 2>/dev/null || true
git push github datum-v1.0.0
```
Watch GitHub → the repo → Actions. Then make the package public: GitHub → your profile → Packages → `blake2b-datum-gateway`
→ Package settings → Change visibility → Public. (Do the same once for `blake2b-asic-control` if it is not public.)
Check: `docker pull ghcr.io/christhealien/blake2b-datum-gateway:1.0.0` works without logging in.

**21. Publish the store**
```
cd ~/umbrel-work/blake2b-store
git remote add github https://github.com/christhealien/blake2b.git
cd ~/umbrel-work/datum-gateway-umbrel
tools/publish_to_store.sh ~/umbrel-work/blake2b-store github master
```
(No `RETARGET_ARGS` here: the files already point at GitHub.)

**22. Tell people**: Umbrel → App Store → ⋯ → Community App Stores → `https://github.com/christhealien/blake2b`.
If the old ASIC repo is also set up as a store, people should add only `blake2b`, otherwise the same app appears twice.
Delete `umbrel-app-store.yml` from `blake2b-asic-control` once you have moved everything.

---

## Part D: updates

**23. A new DATUM Gateway release appears upstream**
* Gitea does it by itself weekly (workflow `upstream-sync`): it checks the new release against the UI, bumps the version, tags it, builds the image and refreshes the Gitea store.
  If the check fails the workflow turns red and tells you which template placeholder or heading changed; fix `datum-app/www/` and push.
* By hand, any time:
```
cd ~/umbrel-work/datum-gateway-umbrel
git pull gitea master
python3 -I tools/sync_upstream.py          # checks, bumps version, prints NEW_VERSION=x.y.z
git add -A && git commit -m "Follow upstream" && git tag datum-vX.Y.Z   # use the printed version
git push gitea master datum-vX.Y.Z         # test first
git push github master datum-vX.Y.Z        # when happy: public image builds
tools/publish_to_store.sh ~/umbrel-work/blake2b-store github master
```
Umbrel offers the update on the app's page once the store repo has the new version.

**24. You changed the UI or packaging (no upstream change)**
```
python3 -I tools/sync_upstream.py --bump "What changed, one line"
git add -A && git commit -m "UI change" && git tag datum-vX.Y.Z && git push gitea master datum-vX.Y.Z
```
then continue as in step 23 (GitHub push, publish_to_store).

**25. Preview UI changes without a node**
```
python3 tools/preview.py            # http://127.0.0.1:7152 with sample data
python3 -I tools/validate_overlay.py --upstream /path/to/a/clone/of/datum_gateway
```
The validator must say `OK` before every release.

**26. Does updating my repo pull CONVOYMining's code?** Not by itself. The image build always fetches the upstream release named in
`UPSTREAM_TAG` (the one the UI was checked against); step 23 moves that forward.

---

## Quick reference

| Task | Command |
|---|---|
| Logs | `sudo docker logs -f blake2b-datum-gateway_web_1` |
| Restart | the **Restart Gateway** button (Config or Status footer), or `sudo docker restart blake2b-datum-gateway_web_1` |
| Reset the login | `sudo rm ~/umbrel/app-data/blake2b-datum-gateway/data/auth.json` then restart |
| Config file | `~/umbrel/app-data/blake2b-datum-gateway/data/config.json` (mode 600; edit with `sudo`) |
| Stratum address | `stratum+tcp://UMBREL:23334` |
