# Setup guide: GitHub is the master, Gitea is an exact copy you pull from

```
your Linux PC  --push-->  GitHub (christhealien)  --pull mirror-->  Gitea (same repos, same files)
                              |  Actions build the image -> ghcr.io
                              +--> Umbrel installs from the store repo (GitHub, or the Gitea copy)
```

Three repos under https://github.com/christhealien/ :

| Repo | Holds |
|---|---|
| `blake2b` | The Umbrel **store** (both app folders). This is the address people add. |
| `blake2b-asic-control` | Source of the ASIC app (exists already). |
| `datum-gateway-umbrel` | Source of the DATUM app (new). |

Gitea gets read-only mirrors of the same three repos. Because the mirror is identical, nothing is rewritten: images always come
from `ghcr.io/christhealien/...` and icons from GitHub. Replace `GITEA` (e.g. `http://192.168.1.50:3000`), `GUSER` (your Gitea user)
and `UMBREL` (e.g. `umbrel.local`) in the commands.

Not tested here (no Docker, Umbrel or C compiler available): the Docker build, running on a real Umbrel, and whether umbrelOS
accepts a Gitea address as a store. Everything else was run or checked.

## Part A: your Linux PC, once

1. Arch Linux:
   ```
   sudo pacman -Syu --needed git python curl github-cli tar
   ```
   (`python` provides the `python3` command. Docker is not needed on your PC; GitHub builds the image.)
2. `gh auth login` (GitHub.com, HTTPS, log in as **christhealien**).
3. `git config --global user.name "christhealien" && git config --global user.email "you@example.com"`
4. Unpack the archives:
   ```
   mkdir -p ~/umbrel-work && cd ~/umbrel-work
   tar xzf ~/Downloads/datum-gateway-umbrel.tar.gz
   tar xzf ~/Downloads/blake2b-store.tar.gz
   ```

## Part B: GitHub (the master copy)

5. **Create the two new repos** (public):
   ```
   gh repo create christhealien/datum-gateway-umbrel --public
   gh repo create christhealien/blake2b --public
   ```
6. **Make a token for the workflows** (they must push to other repos and start other workflows):
   GitHub → Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate.
   Repository access: *Only select* → `datum-gateway-umbrel` and `blake2b`. Permission: **Contents: Read and write**.
   Copy it, then:
   ```
   gh secret set STORE_TOKEN --repo christhealien/datum-gateway-umbrel
   ```
   (paste the token when asked). This lets a new release update the store by itself and lets the weekly upstream check tag releases.
7. **Push the DATUM source repo**
   ```
   cd ~/umbrel-work/datum-gateway-umbrel
   git init -b master && git add -A && git commit -m "DATUM Gateway for Umbrel"
   git remote add origin https://github.com/christhealien/datum-gateway-umbrel.git
   git push -u origin master
   ```
8. **Push the store repo.** It contains both apps (`blake2b-asic-control/` and `blake2b-datum-gateway/`) and `umbrel-app-store.yml` (id `blake2b`).
   ```
   cd ~/umbrel-work/blake2b-store
   git init -b master && git add -A && git commit -m "blake2b store"
   git remote add origin https://github.com/christhealien/blake2b.git
   git push -u origin master
   ```
9. **Build the first image** by tagging a release:
   ```
   cd ~/umbrel-work/datum-gateway-umbrel
   git tag datum-v1.0.0 && git push origin datum-v1.0.0
   ```
   Watch GitHub → `datum-gateway-umbrel` → Actions → *image* (takes a while: it compiles for amd64 and arm64).
10. **Make the image public** (once): GitHub → your profile → Packages → `blake2b-datum-gateway` → Package settings → Change visibility → Public.
    Check from any PC: `docker pull ghcr.io/christhealien/blake2b-datum-gateway:1.0.0` (no login needed). Do the same once for
    `blake2b-asic-control` if its package is not public.
11. **Install on Umbrel** (the Bitcoin app, Knots or Core, must be running): App Store → ⋯ (top right) → Community App Stores →
    paste `https://github.com/christhealien/blake2b` → install **DATUM Gateway (blake2b)**.
12. **First start**: open the app, sign in with the username and password Umbrel shows on the app's page, enter your reward address
    on the setup page, then point your miners at `stratum+tcp://UMBREL:23334`.
13. **The old ASIC repo as a store**: if `blake2b-asic-control` currently doubles as a store, remove the Umbrel store entry for it
    (Community App Stores → remove), add only `blake2b`, and later delete `umbrel-app-store.yml` and the app folder copy from the
    ASIC repo if you like. Two stores with the same app id would show the app twice. Export your miners from the ASIC app first;
    reinstalling an app from another store may start with an empty data folder.

## Part C: Gitea as an exact copy

14. In Gitea create a token: avatar → Settings → Applications → Generate New Token, permission **write:repository**.
15. Create the three mirrors (needs the repo `tools/` folder from step 4):
    ```
    cd ~/umbrel-work/datum-gateway-umbrel
    GITEA=http://192.168.1.50:3000 GUSER=chris GTOKEN=PASTE_TOKEN tools/gitea_mirror.sh create
    ```
    (or by hand in the Gitea web page: **+** → New Migration → GitHub → URL, tick *This repository will be a mirror*).
16. **Pull whenever you want:**
    ```
    GITEA=http://192.168.1.50:3000 GUSER=chris GTOKEN=PASTE_TOKEN tools/gitea_mirror.sh sync
    ```
    or open a repo in Gitea → Settings → Repository → Mirror Settings → **Synchronize now**. They also refresh every 8 hours.
17. **Use the Gitea copy on Umbrel (optional):** Community App Stores → paste `GITEA/GUSER/blake2b`.
    *Unverified:* some umbrelOS versions only take GitHub addresses; if it is refused, keep using the GitHub address (step 11).
    The images still come from ghcr.io, so the Umbrel needs internet access to GitHub's registry either way.

## Part D: updates

18. **New DATUM Gateway release upstream**: automatic. Every Monday GitHub checks CONVOYMining/datum_gateway, tests that the UI still
    fits, bumps the version, tags it, builds the image and updates the store. A red run (GitHub emails you) means upstream changed
    something the UI depends on; the log names it. Run it now: GitHub → Actions → *upstream-sync* → Run workflow.
    Then pull in Gitea (step 16); Umbrel shows the update on the app's page.
19. **You changed the UI or packaging**:
    ```
    cd ~/umbrel-work/datum-gateway-umbrel
    python3 -I tools/validate_overlay.py --upstream /path/to/datum_gateway     # must say OK (git clone https://github.com/CONVOYMining/datum_gateway first)
    python3 -I tools/sync_upstream.py --bump "What changed, one line"          # prints NEW_VERSION=x.y.z
    git add -A && git commit -m "UI change"
    git tag datum-vX.Y.Z                                                         # the printed version
    git push origin master datum-vX.Y.Z
    ```
    The image workflow builds it and updates the store.
20. **Preview UI changes without a node**: `python3 tools/preview.py`, open http://127.0.0.1:7152 (sample data).
21. **ASIC app updates** work as before in its own repo; to refresh its copy in the store:
    ```
    cd ~/umbrel-work/blake2b-store && git pull
    rm -rf blake2b-asic-control && cp -r /path/to/blake2b-asic-control/blake2b-asic-control .
    git add -A && git commit -m "Update ASIC app" && git push
    ```
22. **Does pulling pull CONVOYMining's code?** No. The image builds the upstream release named in `UPSTREAM_TAG` (the one the UI was
    checked against); step 18 moves it forward.

## Troubleshooting (on the Umbrel: `ssh umbrel@UMBREL`)

```
sudo docker ps -a | grep datum
sudo docker logs --tail 100 blake2b-datum-gateway_web_1
sudo docker restart blake2b-datum-gateway_web_1
```
* "Waiting for node": the Bitcoin app is syncing or not started; the page says which.
* Forgot the login: `sudo rm ~/umbrel/app-data/blake2b-datum-gateway/data/auth.json && sudo docker restart blake2b-datum-gateway_web_1`.
* Image pull fails: the package is still private (step 10), or the tag has not finished building (Actions).
* Config file: `~/umbrel/app-data/blake2b-datum-gateway/data/config.json` (edit with `sudo`). Restart button: Config or Status footer.
