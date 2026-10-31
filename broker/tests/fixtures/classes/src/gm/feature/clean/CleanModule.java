package gm.feature.clean;

import gm.companion.api.ClientModule;
import gm.companion.api.ModuleContext;
import net.minecraft.client.Minecraft;
import net.minecraft.network.chat.Component;
import net.minecraft.util.ARGB;
import net.minecraft.util.Mth;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/** What a real HUD module does, including everything javac generates: lambdas, concat, records, switches. */
public final class CleanModule implements ClientModule {
	private record Reading(String label, int value) {}

	private enum Mode { QUIET, LOUD }

	private sealed interface Shape permits Dot, Bar {}

	private record Dot(int size) implements Shape {}

	private record Bar(int width) implements Shape {}

	private final List<Reading> readings = new ArrayList<>();
	private final Map<String, Integer> counts = new HashMap<>();
	private final Mode mode = Mode.QUIET;
	private int ticks;

	@Override
	public void enable(ModuleContext context) {
		this.counts.merge(getClass().getSimpleName(), 1, Integer::sum);
		this.readings.add(new Reading("start", this.counts.size()));
		context.onClientTick(client -> this.ticks++);
		context.onHud((graphics, deltaTracker) -> {
			if (this.ticks < 0) {
				throw new IllegalStateException("negative ticks in " + context.moduleId());
			}
			String label = switch (this.mode) {
				case QUIET -> "quiet";
				case LOUD -> "loud";
			};
			Shape shape = this.ticks % 2 == 0 ? new Dot(2) : new Bar(4);
			int size = switch (shape) {
				case Dot dot -> dot.size();
				case Bar bar -> bar.width();
			};
			graphics.fill(4, 4, 220, 22 + size, ARGB.opaque(0x200040));
			graphics.text(Minecraft.getInstance().font, Component.literal(label + " " + this.readings), 8, 9,
					Mth.clamp(this.ticks, 0, 255));
		});
	}
}
