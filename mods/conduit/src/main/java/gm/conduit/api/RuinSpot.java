package gm.conduit.api;

import net.minecraft.core.BlockPos;

/**
 * Where a ruin is, or may turn up.
 *
 * @param pos its corner. For one that's there, that's exactly where it is. For one that isn't yet, the height is a good guess from
 *            how the land will generate, and it may yet turn out not to suit the ruin, so there may be nothing there in the end
 * @param placed whether it's really there
 */
public record RuinSpot(BlockPos pos, boolean placed) {}
