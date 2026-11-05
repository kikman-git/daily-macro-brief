import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  webpack: (config, { isServer }) => {
    if (isServer) {
      // webpack's builtin-module list predates node:sqlite; keep it external
      config.externals = [
        ...(config.externals ?? []),
        { "node:sqlite": "node-commonjs node:sqlite" },
      ];
    }
    return config;
  },
};

export default nextConfig;
