{
  description = "Development environment for Kindle OpenDisplay and Kindle Inkwell";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    crane.url = "github:ipetkov/crane";
    inkwell = {
      url = "github:akaped/Inkwell/29cc6d02c14c6897fe47356d228b318c846fdfcd";
      flake = false;
    };
    rust-overlay = {
      url = "github:oxalica/rust-overlay";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs =
    {
      crane,
      inkwell,
      nixpkgs,
      rust-overlay,
      ...
    }:
    let
      eachSystem = nixpkgs.lib.genAttrs [
        "x86_64-linux"
        "aarch64-linux"
      ];
    in
    rec {
      hydraJobs = eachSystem (system: packages.${system} // checks.${system});

      packages = eachSystem (
        system:
        let
          pkgs = import nixpkgs {
            inherit system;
            overlays = [ rust-overlay.overlays.default ];
          };
          target = "armv7-unknown-linux-musleabihf";
          toolchain = pkgs.rust-bin.stable."1.99.1".minimal.override {
            targets = [ target ];
          };
          craneLib = (crane.mkLib pkgs).overrideToolchain toolchain;
          src = craneLib.cleanCargoSource ./.;
          common = {
            inherit src;
            doCheck = false;
            CARGO_BUILD_TARGET = target;
            RUSTFLAGS = "-C linker=rust-lld -C link-self-contained=yes";
          };
        in
        rec {
          inkwell-pw4 = import ./nix/inkwell.nix {
            inherit pkgs;
            upstream = inkwell;
            receiver = kindle-armv7;
          };

          kindle-armv7 = craneLib.buildPackage (
            common
            // {
              cargoArtifacts = craneLib.buildDepsOnly common;
              nativeBuildInputs = [ pkgs.file ];
              postInstall = ''
                file "$out/bin/kindle-opendisplay" | grep -E 'ELF 32-bit .* ARM.*(statically linked|static-pie linked)'
              '';
            }
          );
        }
      );

      checks = eachSystem (
        system:
        let
          pkgs = nixpkgs.legacyPackages.${system};
          craneLib = crane.mkLib pkgs;
          src = craneLib.cleanCargoSource ./.;
          cargoArtifacts = craneLib.buildDepsOnly { inherit src; };
          python = pkgs.python3.withPackages (ps: [
            ps.bumble
            ps.cryptography
          ]);
        in
        {
          protocol = craneLib.cargoTest { inherit src cargoArtifacts; };

          # Virtual BLE test of the ARMv7 receiver under qemu-user. The build
          # user is not root, so the test expects remote commands disabled.
          virtual-hci-armv7 =
            pkgs.runCommand "kindle-opendisplay-virtual-hci-armv7"
              {
                nativeBuildInputs = [
                  pkgs.qemu-user
                  python
                ];
              }
              ''
                python3 ${./tests/virtual_hci.py} \
                  qemu-arm -cpu cortex-a9 \
                  ${packages.${system}.kindle-armv7}/bin/kindle-opendisplay
                touch "$out"
              '';
        }
      );

      devShells = eachSystem (
        system:
        let
          pkgs = nixpkgs.legacyPackages.${system};
        in
        {
          default = pkgs.mkShell {
            packages = [
              pkgs.black
              pkgs.cargo
              pkgs.clippy
              pkgs.nixfmt
              pkgs.python314
              pkgs.ruff
              pkgs.rustc
              pkgs.rustfmt
              pkgs.shellcheck
              pkgs.uv
            ];
          };
        }
      );
    };
}
