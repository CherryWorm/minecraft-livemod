package gm.companion.api;

import net.fabricmc.fabric.api.client.rendering.v1.hud.HudElement;
import net.minecraft.client.Minecraft;

import java.util.function.Consumer;

/** What a module can hook into. This grows as modules need more, and a change here needs a companion update. */
public interface ModuleContext {
	String moduleId();

	int generation();

	void onHud(HudElement element);

	void onClientTick(Consumer<Minecraft> tick);
}
