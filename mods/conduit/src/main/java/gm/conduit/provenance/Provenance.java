package gm.conduit.provenance;

import com.mojang.serialization.Codec;
import gm.conduit.Conduit;
import net.fabricmc.fabric.api.attachment.v1.AttachmentRegistry;
import net.fabricmc.fabric.api.attachment.v1.AttachmentType;
import net.minecraft.core.BlockPos;
import net.minecraft.resources.Identifier;
import net.minecraft.world.level.chunk.ChunkAccess;
import net.minecraft.world.level.chunk.LevelChunk;

import java.util.HashSet;
import java.util.List;
import java.util.Set;

/**
 * Tells natural blocks from changed ones, which the game itself can't do. Everything is stored in the
 * chunk's own save data, so blocks and these records are always written together, even across a crash.
 */
public final class Provenance {
	public static final AttachmentType<TouchedBlocks> TOUCHED = AttachmentRegistry.createPersistent(
			Identifier.fromNamespaceAndPath(Conduit.NAMESPACE, "touched"), TouchedBlocks.CODEC);

	/** Patches already applied to this chunk. Stored as a list because that's how the codec writes it. */
	public static final AttachmentType<List<String>> APPLIED_PATCHES = AttachmentRegistry.createPersistent(
			Identifier.fromNamespaceAndPath(Conduit.NAMESPACE, "applied_patches"), Codec.STRING.listOf());

	private Provenance() {}

	/**
	 * Must run at mod init. Attachment types register when this class first loads, and chunks read from
	 * disk before that silently lose their saved data, which would erase what players have built.
	 */
	public static void init() {}

	/** Called for every block change on a live chunk. Worldgen writes to proto chunks and never gets here. */
	public static void recordChange(LevelChunk chunk, BlockPos pos) {
		TouchedBlocks touched = chunk.getAttached(TOUCHED);
		if (touched == null) {
			touched = new TouchedBlocks();
			chunk.setAttached(TOUCHED, touched);
		}
		touched.mark(pos);
	}

	public static boolean isTouched(ChunkAccess chunk, BlockPos pos) {
		TouchedBlocks touched = chunk.getAttached(TOUCHED);
		return touched != null && touched.contains(pos);
	}

	public static boolean hasAnyTouched(ChunkAccess chunk) {
		TouchedBlocks touched = chunk.getAttached(TOUCHED);
		return touched != null && !touched.isEmpty();
	}

	public static Set<String> appliedPatches(ChunkAccess chunk) {
		List<String> applied = chunk.getAttached(APPLIED_PATCHES);
		return applied == null ? Set.of() : new HashSet<>(applied);
	}

	public static void markApplied(ChunkAccess chunk, Set<String> patches) {
		chunk.setAttached(APPLIED_PATCHES, List.copyOf(patches));
	}
}
