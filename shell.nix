# Blender dev shell for the procedural-city rebuild (blender/).
#
# PINNED. This resolves to exactly one nixpkgs tree, and therefore exactly one
# Blender closure — the same 851 MiB that is already in the local store. Entering
# this shell must never re-download anything.
#
# Verified on this machine:
#   nixpkgs  flakehub nixpkgs-weekly 0.1.1042126, rev 624af665418d3c65d544145b4d34ad696439570e
#   blender  5.2.0 LTS, aarch64-darwin
#   store    /nix/store/dcga32d59a06hjwvfi1lxzp55v43wah1-blender-5.2.0
#   cycles   METAL backend, "Apple M2 Max (GPU - 38 cores)"
#
# The whole closure is substitutable from cache.nixos.org — nothing compiles.
#
# The pinned tree is ALSO protected from garbage collection by a GC root at
# `.nix-gcroot-blender` (gitignored) in the repo root. That matters here: this
# machine is disk-constrained, and `nix-collect-garbage -d` is on the list of
# reclaim options. Without that root, a GC would silently delete Blender and the
# next `nix-shell` would re-download the lot. Re-create it after any GC with:
#
#   nix-build shell.nix -A blender -o .nix-gcroot-blender
#
# To move to a newer nixpkgs, change BOTH `url` and `sha256` together (get the
# pair from `nix flake metadata nixpkgs --json`, fields locked.url / locked.narHash),
# then re-verify that `blender --version` still reports a Cycles METAL device.
{
  # This is the *flakehub weekly* tree that `<nixpkgs>` resolves to on this
  # machine, and it is deliberately NOT the nixpkgs registry tarball. That
  # distinction is the whole point: the registry tarball
  # (nixpkgs-26.11pre1049336) evaluates blender to
  # /nix/store/9984fabjig1kzg9pkvphg1xmja3vm0lb-blender-5.2.0 — a different
  # derivation from the one already built here, so pinning to it would silently
  # re-download the entire 851 MiB closure. Verified by evaluating both.
  #
  # locked.url / locked.narHash from:
  #   nix flake metadata 'https://flakehub.com/f/DeterminateSystems/nixpkgs-weekly/*.tar.gz' --json
  nixpkgs ? builtins.fetchTarball {
    url = "https://api.flakehub.com/f/pinned/DeterminateSystems/nixpkgs-weekly/0.1.1042126%2Brev-624af665418d3c65d544145b4d34ad696439570e/019fcb6c-e772-7cb3-baa0-211e12b79e38/source.tar.gz";
    sha256 = "sha256-m0pDuRJG7EDo9ri+4Ksu83VsI+PlxNC9lNBfydejce4=";
  },
  pkgs ? import nixpkgs { },
}:

pkgs.mkShell {
  name = "richard-blender-city";

  buildInputs = [
    pkgs.blender
  ];

  shellHook = ''
    echo "richard-blender-city: $(blender --version 2>/dev/null | head -n1 || echo 'blender not found on PATH')"
    echo "  render:  blender --background --python blender/build_city.py -- --preset dusk"
    echo "  presets: noon dusk night tiltshift"
  '';
}
