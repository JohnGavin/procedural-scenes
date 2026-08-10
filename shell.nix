# Blender dev shell for the procedural-city rebuild (blender/).
#
# TODO: pin to explicit rev. This worktree has no network access, so we
# cannot run `nix-prefetch-url` to get a real sha256 for a pinned
# `builtins.fetchTarball { url = ...; sha256 = ...; }` — and a wrong/fake
# hash is worse than this honest TODO (it would either fail loudly or,
# worse, silently resolve to whatever happens to hash-match). Substitute the
# block below with something like:
#
#   let
#     pkgs = import (builtins.fetchTarball {
#       url = "https://github.com/NixOS/nixpkgs/archive/<commit-sha>.tar.gz";
#       sha256 = "<sha256 from `nix-prefetch-url --unpack <url>`>";
#     }) {};
#   in
#
# once a rev known to build `blender` (5.2.x on aarch64-darwin) has been
# verified with network access. Until then this falls back to the channel
# already configured as <nixpkgs> on this machine, which is NOT
# reproducible across machines/time — that is the whole point of pinning.
{ pkgs ? import <nixpkgs> { } }:

pkgs.mkShell {
  name = "richard-blender-city";

  buildInputs = [
    pkgs.blender
  ];

  shellHook = ''
    echo "richard-blender-city: blender $(blender --version 2>/dev/null | head -n1 || echo 'not found on PATH')"
  '';
}
