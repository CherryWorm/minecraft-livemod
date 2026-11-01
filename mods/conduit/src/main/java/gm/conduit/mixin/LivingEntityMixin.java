package gm.conduit.mixin;

import com.llamalad7.mixinextras.sugar.Local;
import com.llamalad7.mixinextras.sugar.ref.LocalDoubleRef;
import com.llamalad7.mixinextras.sugar.ref.LocalFloatRef;
import gm.conduit.modules.ServerModuleHost;
import net.minecraft.server.level.ServerLevel;
import net.minecraft.tags.DamageTypeTags;
import net.minecraft.world.damagesource.DamageSource;
import net.minecraft.world.entity.LivingEntity;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfoReturnable;

/** Every hit on anything living comes through here, players and mobs alike. Fabric's own events can only say whether it happens, not how hard. */
@Mixin(LivingEntity.class)
abstract class LivingEntityMixin {
	@Inject(method = "hurtServer", at = @At("HEAD"), cancellable = true)
	private void conduit$changeDamage(ServerLevel level, DamageSource source, float damage, CallbackInfoReturnable<Boolean> info, @Local(argsOnly = true) LocalFloatRef amount) {
		LivingEntity target = (LivingEntity) (Object) this;
		if (source.is(DamageTypeTags.BYPASSES_INVULNERABILITY) || target.isInvulnerableTo(level, source) || target.isDeadOrDying()) {
			return;
		}
		float said = ServerModuleHost.instance().damage(target, source, damage);
		if (said <= 0 && damage > 0) {
			info.setReturnValue(false);
		}
		amount.set(said);
	}

	@Inject(method = "knockback(DDDLnet/minecraft/world/damagesource/DamageSource;FZ)V", at = @At("HEAD"))
	private void conduit$changeKnockback(double power, double x, double z, DamageSource source, float damage, boolean fromEffect, CallbackInfo info, @Local(argsOnly = true, ordinal = 0) LocalDoubleRef strength) {
		if (!((LivingEntity) (Object) this).level().isClientSide()) {
			strength.set(ServerModuleHost.instance().knockback((LivingEntity) (Object) this, source, power));
		}
	}
}
