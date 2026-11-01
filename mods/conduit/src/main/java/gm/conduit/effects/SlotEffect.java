package gm.conduit.effects;

import eu.pb4.polymer.core.api.other.PolymerMobEffect;
import gm.conduit.api.EffectBehavior;
import gm.conduit.modules.ServerModuleHost;
import net.minecraft.server.level.ServerLevel;
import net.minecraft.world.effect.MobEffect;
import net.minecraft.world.effect.MobEffectCategory;
import net.minecraft.world.entity.LivingEntity;

/** A blank status effect. A client has no idea what one is, so Polymer stops the game mentioning it to them, and SlotEffects tells a companion instead. */
public final class SlotEffect extends MobEffect implements PolymerMobEffect {
	private final String slotId;

	SlotEffect(String slotId) {
		super(MobEffectCategory.NEUTRAL, SlotEffects.NO_COLOUR);
		this.slotId = slotId;
	}

	public String slotId() {
		return this.slotId;
	}

	@Override
	public int getColor() {
		return SlotEffects.definition(this.slotId).color();
	}

	@Override
	public MobEffectCategory getCategory() {
		return SlotEffects.definition(this.slotId).category();
	}

	@Override
	public boolean shouldApplyEffectTickThisTick(int duration, int amplifier) {
		return ServerModuleHost.instance().effectBehavior(this.slotId) != null;
	}

	@Override
	public boolean applyEffectTick(ServerLevel level, LivingEntity entity, int amplifier) {
		EffectBehavior behavior = ServerModuleHost.instance().effectBehavior(this.slotId);
		if (behavior != null) {
			ServerModuleHost.instance().guarded(this.slotId, () -> behavior.tick(entity, amplifier));
		}
		return true;
	}

	@Override
	public void onEffectStarted(LivingEntity entity, int amplifier) {
		EffectBehavior behavior = ServerModuleHost.instance().effectBehavior(this.slotId);
		if (behavior != null) {
			ServerModuleHost.instance().guarded(this.slotId, () -> behavior.started(entity, amplifier));
		}
	}

	/** Called for anything that's just lost this. The game's own hook for this hears nothing about who. */
	public void ended(LivingEntity entity) {
		EffectBehavior behavior = ServerModuleHost.instance().effectBehavior(this.slotId);
		if (behavior != null) {
			ServerModuleHost.instance().guarded(this.slotId, () -> behavior.ended(entity));
		}
	}
}
