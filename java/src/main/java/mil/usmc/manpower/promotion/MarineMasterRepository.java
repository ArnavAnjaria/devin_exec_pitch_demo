package mil.usmc.manpower.promotion;

import java.util.Optional;

/**
 * Lookup of MARINE_MASTER rows.
 *
 * RECONSTRUCTED from the single call site in EligibilityService.
 */
public interface MarineMasterRepository {

    Optional<MarineMaster> findByEdipi(long edipi);
}
