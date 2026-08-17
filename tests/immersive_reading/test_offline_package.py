import pytest
from deeptutor.immersive_reading.service import ImmersiveReadingService

@pytest.mark.asyncio
async def test_export_offline_package_creates_zip_with_required_files(
    reading_service: ImmersiveReadingService, imported_document: dict
) -> None:
    doc_id = imported_document["id"]
    
    # Export the offline package
    package_path = await reading_service.export_offline_package(doc_id)
    
    assert package_path.exists()
    assert package_path.suffix == ".zip"
    
    import zipfile
    with zipfile.ZipFile(package_path, "r") as zf:
        namelist = zf.namelist()
        assert "manifest.json" in namelist
        assert "translations.json" in namelist
        assert "ecdict_subset.json" in namelist
        assert any(name.startswith("sections/") for name in namelist)

