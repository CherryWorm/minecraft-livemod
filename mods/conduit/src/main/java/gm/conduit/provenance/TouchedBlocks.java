package gm.conduit.provenance;

import com.mojang.serialization.Codec;
import net.minecraft.core.BlockPos;

import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * Which blocks in one chunk have changed since it generated, as one bitset per section that has any.
 * Most chunks have few changes, so this stays small. Saved with the chunk, so it can't disagree with
 * the blocks it describes.
 */
public final class TouchedBlocks {
	private static final int WORDS = 4096 / Long.SIZE;

	private record Section(int y, List<Long> bits) {
		static final Codec<Section> CODEC = com.mojang.serialization.codecs.RecordCodecBuilder.create(i -> i.group(
				Codec.INT.fieldOf("y").forGetter(Section::y),
				Codec.LONG.listOf().fieldOf("bits").forGetter(Section::bits)
		).apply(i, Section::new));
	}

	public static final Codec<TouchedBlocks> CODEC = Section.CODEC.listOf().xmap(TouchedBlocks::fromSections, TouchedBlocks::toSections);

	private final Map<Integer, long[]> sections = new HashMap<>();

	public boolean mark(BlockPos pos) {
		int index = indexOf(pos);
		long[] bits = this.sections.computeIfAbsent(pos.getY() >> 4, y -> new long[WORDS]);
		long mask = 1L << (index % Long.SIZE);
		boolean changed = (bits[index / Long.SIZE] & mask) == 0;
		bits[index / Long.SIZE] |= mask;
		return changed;
	}

	public boolean contains(BlockPos pos) {
		long[] bits = this.sections.get(pos.getY() >> 4);
		if (bits == null) {
			return false;
		}
		int index = indexOf(pos);
		return (bits[index / Long.SIZE] & (1L << (index % Long.SIZE))) != 0;
	}

	public boolean isEmpty() {
		return this.sections.isEmpty();
	}

	private static int indexOf(BlockPos pos) {
		return (pos.getY() & 15) << 8 | (pos.getZ() & 15) << 4 | (pos.getX() & 15);
	}

	private static TouchedBlocks fromSections(List<Section> list) {
		TouchedBlocks out = new TouchedBlocks();
		for (Section section : list) {
			long[] bits = new long[WORDS];
			for (int i = 0; i < Math.min(WORDS, section.bits().size()); i++) {
				bits[i] = section.bits().get(i);
			}
			out.sections.put(section.y(), bits);
		}
		return out;
	}

	private List<Section> toSections() {
		return this.sections.entrySet().stream()
				.map(entry -> new Section(entry.getKey(), java.util.Arrays.stream(entry.getValue()).boxed().toList()))
				.toList();
	}
}
